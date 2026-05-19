"""
tasks/ingestion_task.py — Emthethal AI
=======================================
RQ worker task: Full document ingestion pipeline (async).

This runs inside the rq-worker container, NOT in the FastAPI process.
FastAPI enqueues via async_queue.enqueue_ingestion().
The worker executes this function, relieving FastAPI from OCR timeouts.

Pipeline:
  1. Extract (OCR / native parser via core/extractor.py)
  2. LLM Normalize (core/llm_normalizer.py)
  3. Confidence Governance evaluation
  4. Build CanonicalFormSchema (core/canonical_schema.py)
  5. Quarantine Gate (core/rag_integrator.py)
  6. Store to Vector DB + SQL
  7. Update lifecycle state (QA state machine)
"""

import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


def run_ingestion_pipeline(
    file_bytes: bytes,
    filename: str,
    department: str,
    device_name: str,
    form_type: str,
    document_type: str = "medical_form",
) -> Dict[str, Any]:
    """
    Full ingestion pipeline. Runs synchronously inside an RQ worker.
    Returns a result dict written to Redis for status polling.

    Note: Uses synchronous DB access (psycopg2) because RQ workers
    are not async. AsyncSession is only for FastAPI request handlers.
    """
    import time
    from ..core.extractor import file_extractor
    from ..core.confidence_governance import confidence_governor
    from ..core.qa_state_machine import form_state_machine, FormLifecycleState

    start = time.time()
    result: Dict[str, Any] = {
        "filename":    filename,
        "department":  department,
        "device_name": device_name,
        "form_type":   form_type,
    }

    try:
        # ── Step 1: Extract ──────────────────────────────────────────────
        # file_extractor.extract() is async-native; use asyncio.run() in worker
        import asyncio
        doc_output = asyncio.run(
            file_extractor.extract(Path(filename), file_bytes)
        )
        logger.info(f"[ingestion] Extracted {doc_output.total_blocks} blocks from '{filename}'")

        # ── Step 2: LLM Normalize ────────────────────────────────────────
        from ..core.llm_normalizer import llm_normalizer
        try:
            doc_output = asyncio.run(llm_normalizer.normalize_document(doc_output))
        except Exception as e:
            logger.warning(f"[ingestion] LLM normalization skipped (non-critical): {e}")

        # ── Step 3: Confidence Governance ────────────────────────────────
        # Collect block-level confidences from doc_output
        block_confidences = [
            b.confidence
            for page in doc_output.pages
            for b in page.blocks
            if hasattr(b, "confidence") and b.confidence is not None
        ]
        gov_result = confidence_governor.evaluate_from_blocks(
            confidences=block_confidences,
            document_id=None,
            form_title=filename,
        )
        result["confidence_outcome"] = gov_result.outcome.value
        result["avg_confidence"]     = gov_result.avg_confidence
        result["recommendation"]     = gov_result.recommendation

        logger.info(
            f"[ingestion] Confidence governance: {gov_result.outcome.value} "
            f"(avg={gov_result.avg_confidence:.3f}) for '{filename}'"
        )

        # ── Step 4: Pydantic V2 Validation ───────────────────────────────
        from ..ingestion_models.schemas import DocumentOutput
        doc_output = DocumentOutput.model_validate(doc_output.model_dump())

        # ── Step 5: Quarantine Check ─────────────────────────────────────
        # Synchronous DB session for worker context
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        import os

        sync_url = os.getenv("DATABASE_URL", "").replace("+asyncpg", "")
        engine = create_engine(sync_url)
        Session = sessionmaker(bind=engine)

        with Session() as session:
            chunks_stored = 0
            quarantine_flag = gov_result.outcome.value == "QUARANTINE"

            # ── Step 6: Persist IngestedDocument record ───────────────────
            from ..models import IngestedDocument
            doc_record = IngestedDocument(
                source_filename=filename,
                file_type=Path(filename).suffix.lstrip("."),
                document_type=document_type,
                department=department,
                device_name=device_name,
                form_type=form_type,
                status="quarantine" if quarantine_flag else "pass",
                quarantine_flag=quarantine_flag,
                avg_confidence=str(gov_result.avg_confidence),
                total_blocks=doc_output.total_blocks,
                processing_metadata={
                    "confidence_outcome": gov_result.outcome.value,
                    "recommendation":     gov_result.recommendation,
                    "thresholds": gov_result.metadata,
                },
            )
            session.add(doc_record)
            session.commit()
            session.refresh(doc_record)

        elapsed = round((time.time() - start) * 1000, 2)
        result.update({
            "status":         "quarantined" if quarantine_flag else "pass",
            "chunks_stored":  chunks_stored,
            "processing_time_ms": elapsed,
        })

        logger.info(f"[ingestion] Complete: {result['status']} in {elapsed}ms")
        return result

    except Exception as e:
        elapsed = round((time.time() - start) * 1000, 2)
        logger.error(f"[ingestion] Pipeline failed for '{filename}': {e}", exc_info=True)
        result.update({"status": "error", "error": str(e), "processing_time_ms": elapsed})
        raise  # RQ will mark the job as failed
