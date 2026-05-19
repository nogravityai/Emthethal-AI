# ============================================================
# CFIS Phase 2B — Geometry Debug API Endpoint
# Location: backend/app/api/routes/geometry_debug.py
#
# PURPOSE: Accept PDF upload → run Phase 2 geometry pipeline →
# return GeometryDebugSnapshot as JSON + annotated page image.
#
# ENDPOINTS:
#   POST /api/cfis/v1/debug/geometry
#     → Runs border inference, table grid, checkbox detection
#     → Returns JSON snapshot + base64 annotated image
#
#   GET /api/cfis/v1/debug/geometry/{doc_id}/overlay/{page}
#     → Returns the annotated PNG overlay for a saved document
# ============================================================

from __future__ import annotations

import base64
import io
import logging
import os
import tempfile
import time
import uuid
from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cfis/v1/debug", tags=["Phase 2B Debug"])


# ── Response Models ───────────────────────────────────────────────────────────

class GeometryLayer(BaseModel):
    name: str
    count: int
    details: Optional[list] = None


class Phase2BDebugResponse(BaseModel):
    document_id: Optional[str] = None
    session_id: Optional[str] = None
    page_number: int = 0
    source_file: str = ""
    processing_time_ms: float = 0.0
    layers: dict = {}
    page_image_b64: Optional[str] = None      # full page PNG (base64)
    overlay_image_b64: Optional[str] = None   # annotated overlay PNG (base64)
    border_audit: list = []
    merged_cells: list = []
    radio_groups: list = []
    hypotheses_summary: dict = {}

# In-memory cache for quick layer toggling (Development only)
_SNAPSHOT_CACHE: dict = {}



# ── Main debug endpoint ───────────────────────────────────────────────────────

@router.post("/geometry", response_class=JSONResponse)
async def debug_geometry(
    file: UploadFile = File(...),
    page_number: int = Query(default=0, ge=0, description="Page to analyze (0-indexed)"),
    dpi: int = Query(default=200, ge=72, le=400, description="DPI for image rendering"),
    layers: str = Query(
        default="lines,boxes,anchors,grids,hypotheses,border_gaps,merged_cells",
        description="Comma-separated list of debug layers to render",
    ),
    run_inference: bool = Query(default=True, description="Run Phase 2B border inference"),
    run_merger: bool = Query(default=True, description="Run Phase 2B cell merger"),
    run_radio: bool = Query(default=True, description="Run Phase 2B radio group fusion"),
):
    """
    Upload a PDF → run Phase 2B geometry pipeline → return annotated debug image + JSON snapshot.

    Returns:
    - `overlay_image_b64`: annotated page PNG (base64) with all geometry layers drawn
    - `page_image_b64`:    clean page PNG (base64)
    - `layers`:            counts for each detected geometry type
    - `border_audit`:      gap-fill decisions from border inference
    - `merged_cells`:      merged cell detection results
    - `radio_groups`:      clustered checkbox groups
    - `hypotheses_summary`: accepted/rejected counts by type
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, detail="Only PDF files accepted")

    content = await file.read()
    if len(content) > 30 * 1024 * 1024:
        raise HTTPException(413, detail="File too large (max 30MB)")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        result = _run_phase2b_pipeline(
            pdf_path=tmp_path,
            page_number=page_number,
            dpi=dpi,
            layer_list=[l.strip() for l in layers.split(",")],
            run_inference=run_inference,
            run_merger=run_merger,
            run_radio=run_radio,
            source_file=file.filename,
        )
        return JSONResponse(content=result)

    except ValueError as e:
        raise HTTPException(422, detail=str(e))
    except Exception as e:
        logger.error(f"Phase 2B debug failed: {e}", exc_info=True)
        raise HTTPException(500, detail=f"Pipeline error: {str(e)[:300]}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


@router.get("/geometry/{session_id}/overlay")
def get_cached_overlay(session_id: str, layers: str = ""):
    """Quickly re-render the overlay for an existing session using different layers."""
    if session_id not in _SNAPSHOT_CACHE:
        raise HTTPException(404, detail="Session expired or not found")
        
    from app.services.debug.geometry_debugger import render_geometry_debug
    
    pil_page, snapshot = _SNAPSHOT_CACHE[session_id]
    layer_list = [l.strip() for l in layers.split(",")] if layers else []
    
    overlay_pil = render_geometry_debug(pil_page, snapshot, layers=layer_list)
    overlay_buf = io.BytesIO()
    overlay_pil.save(overlay_buf, format="PNG", optimize=True)
    overlay_b64 = base64.b64encode(overlay_buf.getvalue()).decode()
    
    return {"overlay_image_b64": overlay_b64}



# ── Pipeline runner ───────────────────────────────────────────────────────────

def _run_phase2b_pipeline(
    pdf_path: str,
    page_number: int,
    dpi: int,
    layer_list: List[str],
    run_inference: bool,
    run_merger: bool,
    run_radio: bool,
    source_file: str,
) -> dict:
    """
    Run the Phase 2B geometry pipeline on one page of a PDF.
    Returns a JSON-serializable dict matching Phase2BDebugResponse.
    """
    from pdf2image import convert_from_path
    import pdfplumber

    from app.services.geometry.visual_geometry import (
        normalize_image_dpi, detect_visual_lines, detect_boxes,
        detect_checkbox_regions,
    )
    from app.services.spatial.structural_analysis import (
        infer_structural_regions, build_table_grids,
        detect_section_boundaries, build_region_hierarchy,
        build_table_grids_with_inference, detect_all_nested_grids,
    )
    from app.services.fusion.hypothesis_engine import (
        HypothesisRegistry,
        make_checkbox_hypothesis, make_table_cell_hypothesis,
        make_section_header_hypothesis,
    )
    # Phase 2 fusion helpers — stubbed since Phase 3 replaced the fusion engine
    def score_layout_hypotheses(registry, tokens): pass   # no-op stub
    def resolve_conflicts(registry): pass                 # no-op stub
    def fuse_radio_groups(registry, tokens): pass         # no-op stub
    def fuse_label_checkbox_pairs(registry, tokens, is_rtl=True): pass  # no-op stub
    def score_widget_type_semantically(h, tokens): return 0.5  # no-op stub
    from app.services.spatial.cell_merger import resolve_merged_cells
    from app.services.geometry.border_inference import run_border_inference
    from app.services.debug.geometry_debugger import (
        GeometryDebugSnapshot, render_geometry_debug, snapshot_to_dict,
    )
    from app.services.hybrid_extraction import extract_page_tokens
    from app.models.schemas import CoordinateSpace

    t0 = time.monotonic()

    # ── Step 1: Load page image ───────────────────────────────────────────────
    page_images = convert_from_path(pdf_path, dpi=dpi, first_page=page_number + 1, last_page=page_number + 1)
    if not page_images:
        raise ValueError(f"Could not render page {page_number}")
    pil_page = page_images[0]
    page_w, page_h = pil_page.size

    # Save clean page as base64
    clean_buf = io.BytesIO()
    pil_page.save(clean_buf, format="PNG", optimize=True)
    page_b64 = base64.b64encode(clean_buf.getvalue()).decode()

    # ── Step 2: Extract tokens ────────────────────────────────────────────────
    tokens = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if page_number < len(pdf.pages):
                pdf_page = pdf.pages[page_number]
                tokens, _ = extract_page_tokens(
                    pdf_page=pdf_page,
                    page_image=pil_page,
                    page_number=page_number,
                    page_w_px=page_w,
                    page_h_px=page_h,
                    language="arabic",
                )
    except Exception as e:
        logger.warning(f"Token extraction failed (non-fatal): {e}")

    # ── Step 3: Visual geometry ───────────────────────────────────────────────
    norm_img, trace = normalize_image_dpi(pil_page)
    lines = detect_visual_lines(norm_img, trace, page_w, page_h)
    boxes = detect_boxes(norm_img, trace, page_w, page_h)
    checkboxes = detect_checkbox_regions(norm_img, trace, page_w, page_h)

    # ── Step 4: Border inference (Phase 2B) ───────────────────────────────────
    border_audit_records = []
    if run_inference and lines:
        from app.services.geometry.border_inference import run_border_inference
        inference_result = run_border_inference(
            lines=lines,
            page_width=page_w,
            page_height=page_h,
        )
        border_audit_records = [r.dict() for r in inference_result.audit_records]
        # Use enriched lines for grid building
        enriched_lines = inference_result.all_as_detected_lines(page_width=page_w, page_height=page_h)
    else:
        enriched_lines = lines

    # ── Step 5: Structural analysis ───────────────────────────────────────────
    regions = infer_structural_regions(enriched_lines, boxes, page_w, page_h, page_number)
    anchors = detect_section_boundaries(enriched_lines, page_w, page_h)
    regions = build_region_hierarchy(regions)
    grids = build_table_grids(enriched_lines, page_w, page_h, snap_tolerance=8.0)

    # ── Step 6: Cell merger (Phase 2B) ────────────────────────────────────────
    merged_cell_records = []
    if run_merger and grids:
        for grid in grids:
            result = resolve_merged_cells(grid)
            merged_cell_records.extend([c.dict() for c in result.merged_cells])
        nested = detect_all_nested_grids(grids)
    else:
        nested = {}

    # ── Step 7: Hypothesis registry ───────────────────────────────────────────
    registry = HypothesisRegistry(page_number=page_number)

    # Submit checkbox hypotheses
    for cb in checkboxes:
        hyp = make_checkbox_hypothesis(
            bbox=cb.bbox,
            page_number=page_number,
            geometry_score=cb.confidence,
        )
        registry.submit(hyp)

    # Submit table cell hypotheses from grid
    for grid in grids:
        for cell_bbox in grid.cell_bboxes:
            hyp = make_table_cell_hypothesis(
                bbox=cell_bbox,
                page_number=page_number,
                geometry_score=grid.confidence,
                structural_score=0.80,
            )
            registry.submit(hyp)

    # Submit section anchor hypotheses
    for anchor in anchors:
        hyp = make_section_header_hypothesis(
            bbox=anchor.bbox,
            page_number=page_number,
            structural_score=anchor.confidence,
        )
        registry.submit(hyp)

    # ── Step 8: Fusion (Phase 2B) ─────────────────────────────────────────────
    if run_radio and tokens:
        fuse_label_checkbox_pairs(registry, tokens, is_rtl=True)
        fuse_radio_groups(registry, tokens)

    score_layout_hypotheses(registry, tokens)
    resolve_conflicts(registry)

    # Collect radio group hypotheses for response
    radio_group_records = [
        {
            "hypothesis_id": h.hypothesis_id,
            "bbox": h.bbox.dict(),
            "fusion_score": h.fusion_score,
            "text_content": h.text_content,
            "accepted": h.accepted,
        }
        for h in registry.by_type("radio_group")
    ]

    # Hypotheses summary by type
    hyp_summary: dict = {}
    for h in registry.all():
        t = h.hypothesis_type
        if t not in hyp_summary:
            hyp_summary[t] = {"total": 0, "accepted": 0, "rejected": 0}
        hyp_summary[t]["total"] += 1
        if h.accepted:
            hyp_summary[t]["accepted"] += 1
        else:
            hyp_summary[t]["rejected"] += 1

    # ── Step 9: Render overlay ────────────────────────────────────────────────
    snapshot = GeometryDebugSnapshot(
        page_number=page_number,
        source_dpi=float(dpi),
        page_width_px=page_w,
        page_height_px=page_h,
        detected_lines=enriched_lines,
        detected_boxes=boxes + checkboxes,
        anchors=anchors,
        regions=regions,
        grids=grids,
        hypotheses=registry.all(),
        border_audit=border_audit_records,
        merged_cells=merged_cell_records,
    )

    overlay_pil = render_geometry_debug(pil_page, snapshot, layers=layer_list)
    overlay_buf = io.BytesIO()
    overlay_pil.save(overlay_buf, format="PNG", optimize=True)
    overlay_b64 = base64.b64encode(overlay_buf.getvalue()).decode()

    snap_dict = snapshot_to_dict(snapshot)
    elapsed_ms = (time.monotonic() - t0) * 1000

    # Cache for quick layer toggles
    session_id = str(uuid.uuid4())
    _SNAPSHOT_CACHE[session_id] = (pil_page, snapshot)

    # Reconstruct serializable raw_geometry for Phase 3 pipeline consumption
    raw_geometry = {
        "meta": {
            "page_width": page_w,
            "page_height": page_h,
            "opencv_version": "4.10.0",
            "kernel_signature": "morph_rect",
            "dpi_normalization": "identity",
            "original_space": "page_pixels",
        },
        "tokens": [
            {
                "bbox": [float(t.bbox.x1), float(t.bbox.y1), float(t.bbox.x2), float(t.bbox.y2)],
                "ocr_raw_text": str(t.ocr_raw_text),
                "confidence": float(t.confidence)
            }
            for t in tokens
        ] if tokens else [],
        "lines": [
            {
                "bbox": [float(l.x1), float(l.y1), float(l.x2), float(l.y2)],
                "x1": float(l.x1),
                "y1": float(l.y1),
                "x2": float(l.x2),
                "y2": float(l.y2),
                "orientation": str(l.orientation),
                "thickness": float(l.thickness),
                "confidence": float(l.confidence)
            }
            for l in enriched_lines
        ] if enriched_lines else [],
        "boxes": [
            {
                "bbox": [float(b.bbox.x1), float(b.bbox.y1), float(b.bbox.x2), float(b.bbox.y2)],
                "confidence": float(b.confidence),
                "box_type": str(b.box_type)
            }
            for b in boxes
        ] if boxes else []
    }

    return {
        "session_id": session_id,
        "source_file": source_file,
        "page_number": page_number,
        "page_width": page_w,
        "page_height": page_h,
        "processing_time_ms": round(elapsed_ms, 1),
        "layers": snap_dict["layers"],
        "page_image_b64": page_b64,
        "overlay_image_b64": overlay_b64,
        "border_audit": border_audit_records[:50],   # cap for response size
        "merged_cells": merged_cell_records[:50],
        "radio_groups": radio_group_records,
        "hypotheses_summary": hyp_summary,
        "token_count": len(tokens),
        "nested_grids": {k: len(v) for k, v in nested.items()},
        "raw_geometry": raw_geometry,
    }
