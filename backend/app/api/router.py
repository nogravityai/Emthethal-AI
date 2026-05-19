# ============================================================
# CFIS API Router v3
# Location: backend/app/api/router.py
# All db.* functions are defined in app.db before use (R11).
# No stubs. No undefined references.
# ============================================================

from __future__ import annotations
import io
import logging
import os
import tempfile
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse, JSONResponse

from app.models.schemas import DocumentOutput, QACorrection
from app.services.ocr import process_pdf
from app.adapters.formio import convert_to_formio
import app.db as db

router = APIRouter(prefix="/api/cfis/v1", tags=["CFIS v3"])
logger = logging.getLogger(__name__)

MAX_FILE_SIZE_MB = 50


@router.get("/health")
async def cfis_health():
    return {
        "status": "ok",
        "version": "3.0",
        "schema": "v2",
        "pipeline": "v3",
        "extraction": "hybrid",
    }


@router.post("/process", response_model=DocumentOutput)
async def process_document(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = None,
    force_ocr: bool = False,
):
    """
    Upload a PDF → hybrid extraction → FormField[] with normalized bboxes.
    Native text extraction is attempted first. OCR is fallback only (R16).
    Page images saved synchronously before temp file deletion.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, detail="Only PDF files accepted (.pdf extension required)")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(413, detail=f"File too large. Maximum: {MAX_FILE_SIZE_MB}MB")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        result = process_pdf(tmp_path, force_ocr=force_ocr)

        # Save page images synchronously BEFORE temp file is deleted
        await _persist_document_with_images(result, tmp_path)

        return result

    except ValueError as e:
        raise HTTPException(422, detail=str(e))
    except Exception as e:
        logger.error(f"Processing failed for {file.filename}: {e}", exc_info=True)
        raise HTTPException(500, detail=f"Processing failed: {str(e)[:200]}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


async def _persist_document_with_images(doc: DocumentOutput, pdf_path: str) -> None:
    """Persist document to DB and render + save page images."""
    try:
        await db.save_document(doc)
        # Auto-approve documents with no QA issues and save formio schema
        if doc.qa_issues_count == 0:
            try:
                await db.approve_document(doc.document_id, "auto")
                approved_doc = await db.get_document(doc.document_id)
                if approved_doc:
                    formio = convert_to_formio(approved_doc)
                    await db.save_formio_schema(doc.document_id, formio)
                    logger.info(f"Auto-approved and saved formio schema for {doc.document_id}")
            except Exception as e:
                logger.warning(f"Auto-approve failed (non-fatal): {e}")
    except Exception as e:
        logger.warning(f"Document DB persist failed (non-fatal): {e}")

    # Save page images — pdf_path still exists at this point
    try:
        from pdf2image import convert_from_path
        images = convert_from_path(pdf_path, dpi=150)  # 150 DPI for preview (smaller)
        for page_num, img in enumerate(images):
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            w, h = img.size
            try:
                await db.save_page_image(doc.document_id, page_num, buf.getvalue(), w, h)
            except Exception as e:
                logger.warning(f"Page {page_num} image save failed: {e}")
            del img
        logger.info(f"Saved {len(images)} page images for {doc.document_id}")
    except Exception as e:
        logger.warning(f"Page image rendering failed for {doc.document_id}: {e}")



@router.get("/documents/{document_id}", response_model=DocumentOutput)
async def get_document(document_id: str):
    doc = await db.get_document(document_id)
    if not doc:
        raise HTTPException(404, detail=f"Document {document_id} not found")
    return doc


@router.get("/documents")
async def list_documents(qa_status: Optional[str] = None):
    return await db.list_documents(qa_status=qa_status)


@router.get("/documents/{document_id}/page/{page_num}/image")
async def get_page_image(document_id: str, page_num: int):
    img_bytes = await db.get_page_image(document_id, page_num)
    if not img_bytes:
        raise HTTPException(
            404,
            detail=f"Page {page_num} image not found for document {document_id}"
        )
    return StreamingResponse(io.BytesIO(img_bytes), media_type="image/png")


@router.post("/qa/correction")
async def submit_correction(correction: QACorrection):
    """
    Submit a human correction for a field.
    Matched by (row_index, column_index, page_number) — geometric identity.
    layout_hash used for template-level propagation in Phase 2.
    """
    await db.save_correction(correction)
    await db.apply_correction(correction.document_id, correction)
    return {
        "status": "saved",
        "correction_id": correction.correction_id,
        "field_id": correction.field_id,
        "matched_by": f"row={correction.row_index},col={correction.column_index},page={correction.page_number}",
    }


@router.post("/qa/approve/{document_id}")
async def approve_document(document_id: str, approved_by: str = "anonymous"):
    """Approve a document after QA. Generates Form.io schema on approval."""
    doc = await db.get_document(document_id)
    if not doc:
        raise HTTPException(404, detail="Document not found")

    unresolved = [f for f in doc.fields if f.needs_qa and not f.human_corrected]
    if unresolved:
        raise HTTPException(
            400,
            detail=(
                f"{len(unresolved)} fields still need QA review. "
                f"First unresolved: '{unresolved[0].semantic_label}'"
            ),
        )

    await db.approve_document(document_id, approved_by)

    # Reload with approved status
    doc = await db.get_document(document_id)
    formio = convert_to_formio(doc)
    await db.save_formio_schema(document_id, formio)

    return {"status": "approved", "formio_ready": True, "document_id": document_id}


@router.get("/qa/pending")
async def list_pending():
    return await db.list_documents(qa_status="pending")


@router.get("/export/formio/{document_id}")
async def export_formio(document_id: str):
    """Export approved document as Form.io JSON schema."""
    schema = await db.get_formio_schema(document_id)
    if not schema:
        # Try to generate on-demand if document is approved
        doc = await db.get_document(document_id)
        if not doc:
            raise HTTPException(404, detail="Document not found")
        if doc.qa_status != "approved":
            raise HTTPException(
                400,
                detail=f"Document not yet approved (status: {doc.qa_status}). Approve first."
            )
        schema = convert_to_formio(doc)
        await db.save_formio_schema(document_id, schema)

    return JSONResponse(content=schema)
