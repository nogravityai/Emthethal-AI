"""
TASK-P3-11 — Thin API Integration Layer

Strict contract:
  routes → PipelineOrchestrator → PipelineContext → Artifact References → Response

Forbidden imports in this file:
  cv2, numpy, paddleocr, easyocr, fusion internals, geometry primitives.
"""
from __future__ import annotations

import logging
import uuid
from threading import Lock
from typing import Dict, Optional, Any, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.pipeline.pipeline_models import generate_stable_id
from app.services.pipeline.pipeline_context import PipelineContext
from app.services.pipeline.orchestration import PipelineOrchestrator
from app.services.pipeline.artifact_store import ArtifactStore

# Stage imports — only Adapters + logical stages, no raw CV/OCR
from app.services.ocr_adapter.adapter import OCRAdapterStage
from app.services.geometry_adapter.adapter import GeometryAdapterStage
from app.services.hitl.evidence_patcher import EvidencePatchStage
from app.services.alignment.engine import AlignmentStage
from app.services.fusion.fusion_engine import AlignmentFusionStage
from app.services.pipeline.pipeline_models import PipelineArtifact

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cfis/v3/pipeline", tags=["CFIS v3 — Pipeline"])

# ── In-process Run Registry ────────────────────────────────────────────────────
# Stores (context, orchestrator) by run_id for replay and artifact access.
# In production: replace with Redis / persistent store.
_run_registry: Dict[str, tuple[PipelineContext, PipelineOrchestrator]] = {}
_registry_lock = Lock()


def _register_run(ctx: PipelineContext, orch: PipelineOrchestrator):
    with _registry_lock:
        _run_registry[ctx.run_id] = (ctx, orch)


def _get_run(run_id: str) -> tuple[PipelineContext, PipelineOrchestrator]:
    entry = _run_registry.get(run_id)
    if not entry:
        raise HTTPException(404, detail=f"Run {run_id} not found. Run may have expired or never existed.")
    return entry


# ── Fixture Stage (for non-PDF fixture runs) ──────────────────────────────────

class _FixtureOCRStage:
    stage_name = "raw_ocr_input"
    required_artifact_types = []
    output_artifact_type = "raw_ocr_dicts"
    def __init__(self, payload): self._p = payload
    def run(self, ctx, store):
        return PipelineArtifact(
            artifact_id=generate_stable_id("api_ocr", str(self._p)),
            artifact_type="raw_ocr_dicts", payload=self._p
        )

class _FixtureGeomStage:
    stage_name = "raw_cv2_data"
    required_artifact_types = []
    output_artifact_type = "raw_cv2_dicts"
    def __init__(self, payload): self._p = payload
    def run(self, ctx, store):
        return PipelineArtifact(
            artifact_id=generate_stable_id("api_geom", str(self._p)),
            artifact_type="raw_cv2_dicts", payload=self._p
        )


# ── Request / Response Models ──────────────────────────────────────────────────

class PipelineRunRequest(BaseModel):
    document_id: str
    input_type: str = "fixture"        # 'pdf' | 'image' | 'fixture'
    pipeline_version: str = "3.0.0"
    # Fixture payloads (used when input_type == 'fixture')
    fixture_ocr: Optional[Dict[str, Any]] = None
    fixture_geometry: Optional[Dict[str, Any]] = None

class PipelineRunResponse(BaseModel):
    run_id: str
    status: str
    document_id: str
    artifacts: Dict[str, str]          # artifact_type → artifact_id

class ReplayRequest(BaseModel):
    run_id: str
    from_stage: str                    # 'alignment' | 'alignment_fusion'

class ReplayResponse(BaseModel):
    run_id: str
    replayed_from: str
    artifacts: Dict[str, str]
    determinism_ok: bool               # True if new IDs == original IDs

class ArtifactInspectResponse(BaseModel):
    artifact_id: str
    artifact_type: str
    schema_version: str
    pipeline_version: str
    derived_from: List[str]
    created_at: str
    payload_summary: Dict[str, Any]    # lightweight summary, not full payload


# ── TASK-P3-11A — Pipeline Run ────────────────────────────────────────────────

@router.post("/run", response_model=PipelineRunResponse)
async def run_pipeline(req: PipelineRunRequest):
    """
    Execute the deterministic evidence pipeline for a document.
    Currently supports 'fixture' input type (direct token/region payloads).
    PDF input wiring comes in TASK-P3-12.
    """
    if req.input_type != "fixture":
        raise HTTPException(400, detail=f"input_type '{req.input_type}' not yet supported. Use 'fixture'.")

    if not req.fixture_ocr or not req.fixture_geometry:
        raise HTTPException(400, detail="fixture_ocr and fixture_geometry are required for input_type='fixture'.")

    ctx = PipelineContext(document_id=req.document_id, pipeline_version=req.pipeline_version)
    orch = PipelineOrchestrator()

    orch.add_stage(_FixtureOCRStage(req.fixture_ocr))
    orch.add_stage(_FixtureGeomStage(req.fixture_geometry))
    orch.add_stage(OCRAdapterStage())
    orch.add_stage(GeometryAdapterStage())
    orch.add_stage(EvidencePatchStage())
    orch.add_stage(AlignmentStage())
    orch.add_stage(AlignmentFusionStage())

    try:
        orch.run_pipeline(ctx)
    except Exception as e:
        logger.error(f"Pipeline failed for {req.document_id}: {e}", exc_info=True)
        raise HTTPException(500, detail=f"Pipeline execution failed: {str(e)[:300]}")

    _register_run(ctx, orch)

    return PipelineRunResponse(
        run_id=ctx.run_id,
        status="completed",
        document_id=req.document_id,
        artifacts=ctx.artifact_references,
    )


# ── TASK-P3-11B — Replay ──────────────────────────────────────────────────────

@router.post("/replay", response_model=ReplayResponse)
async def replay_pipeline(req: ReplayRequest):
    """
    Rerun the pipeline from a specific stage using stored artifacts.
    Asserts that output artifact IDs are identical to the original run (determinism check).
    """
    ctx, orch = _get_run(req.run_id)

    # Snapshot original resolved_fields ID before replay
    orig_resolved = ctx.artifact_references.get("resolved_fields")

    # Clear downstream references to allow rerun
    stages_to_clear = ["alignment_evidence", "resolved_fields"]
    if req.from_stage == "alignment":
        stages_to_clear = ["alignment_evidence", "resolved_fields"]
    elif req.from_stage == "alignment_fusion":
        stages_to_clear = ["resolved_fields"]

    for s in stages_to_clear:
        ctx.artifact_references.pop(s, None)

    try:
        orch.rerun_from_stage(ctx, req.from_stage)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    except Exception as e:
        logger.error(f"Replay failed: {e}", exc_info=True)
        raise HTTPException(500, detail=f"Replay failed: {str(e)[:300]}")

    new_resolved = ctx.artifact_references.get("resolved_fields")
    determinism_ok = (orig_resolved == new_resolved)

    if not determinism_ok:
        logger.error(f"DETERMINISM BREACH: run={req.run_id} orig={orig_resolved} new={new_resolved}")

    return ReplayResponse(
        run_id=req.run_id,
        replayed_from=req.from_stage,
        artifacts=ctx.artifact_references,
        determinism_ok=determinism_ok,
    )


# ── TASK-P3-11C — Artifact Inspection ────────────────────────────────────────

@router.get("/artifacts/{artifact_id}", response_model=ArtifactInspectResponse)
async def inspect_artifact(artifact_id: str):
    """
    Retrieve artifact metadata and a lightweight payload summary.
    Full payload is intentionally omitted — use debug endpoints for that.
    """
    # Search all known runs for this artifact
    artifact = None
    for ctx, orch in _run_registry.values():
        artifact = orch.store.get(artifact_id)
        if artifact:
            break

    if not artifact:
        raise HTTPException(404, detail=f"Artifact {artifact_id} not found in any active run.")

    # Build lightweight summary (no raw pixel data, no huge token arrays)
    payload = artifact.payload
    summary: Dict[str, Any] = {"type": type(payload).__name__}
    if isinstance(payload, list):
        summary["count"] = len(payload)
        if payload:
            first = payload[0]
            summary["first_id"] = getattr(first, "stable_id",
                                   getattr(first, "evidence_id",
                                   getattr(first, "hypothesis_id", "?")))
    elif isinstance(payload, dict):
        summary["keys"] = list(payload.keys())

    return ArtifactInspectResponse(
        artifact_id=artifact.artifact_id,
        artifact_type=artifact.artifact_type,
        schema_version=artifact.schema_version,
        pipeline_version=artifact.pipeline_version,
        derived_from=artifact.derived_from,
        created_at=artifact.created_at,
        payload_summary=summary,
    )


# ── TASK-P3-11D — Debug Snapshot ──────────────────────────────────────────────

from app.services.schema.schema_builder import build_canonical_document
from app.services.schema.adapters.formio_adapter import export_to_formio

@router.get("/export/{run_id}")
async def export_run(run_id: str):
    """
    Exports the final resolved fields into the Canonical Document Schema and Form.io format.
    """
    ctx, orch = _get_run(run_id)
    
    # We fetch the resolved fields artifact
    rf_id = ctx.artifact_references.get("resolved_fields")
    if not rf_id:
        raise HTTPException(404, detail="Run has no resolved fields.")
        
    resolved_fields = orch.store.get(rf_id).payload
    
    # Build Canonical
    canonical_doc = build_canonical_document(ctx.document_id, resolved_fields)
    
    # Export to Form.io
    formio_schema = export_to_formio(canonical_doc)
    
    return {
        "canonical_document": canonical_doc.model_dump(),
        "formio_schema": formio_schema
    }

@router.get("/runs")
async def list_runs():
    """List all recent runs."""
    with _registry_lock:
        return [{"run_id": rid, "status": data["status"]} for rid, data in _run_registry.items()]

@router.get("/runs/{run_id}/timeline")
async def get_run_timeline(run_id: str):
    """Return the structural graph of a run's execution and generated artifacts."""
    ctx, orch = _get_run(run_id)
    
    stages = []
    # For a deterministic pipeline, the orchestrator's stages dictate the flow.
    for st in orch.stages:
        # We look up the artifact produced by this stage if it exists
        out_ref = ctx.artifact_references.get(st.output_artifact_type)
        if out_ref:
            stages.append({
                "stage_name": st.stage_name,
                "output_type": st.output_artifact_type,
                "artifact_id": out_ref
            })
            
    return {
        "run_id": run_id,
        "document_id": ctx.document_id,
        "stages": stages,
        "human_operations": [] # Will wire to HITL ledger in future updates
    }

@router.get("/debug/{run_id}/{stage}")
async def get_debug_snapshot(run_id: str, stage: str):
    """
    Return a structured debug snapshot for a specific pipeline stage.
    Does not re-run the pipeline — reads stored artifacts only.
    """
    ctx, orch = _get_run(run_id)

    stage_map = {
        "ocr":        "ocr_evidence",
        "geometry":   "geometry_evidence",
        "alignment":  "alignment_evidence",
        "fusion":     "resolved_fields",
    }

    artifact_type = stage_map.get(stage)
    if not artifact_type:
        raise HTTPException(400, detail=f"Unknown stage '{stage}'. Valid: {list(stage_map.keys())}")

    artifact_id = ctx.artifact_references.get(artifact_type)
    if not artifact_id:
        raise HTTPException(404, detail=f"Stage '{stage}' artifact not found in run {run_id}.")

    artifact = orch.store.get(artifact_id)
    if not artifact:
        raise HTTPException(404, detail=f"Artifact {artifact_id} missing from store.")

    payload = artifact.payload
    snapshot: Dict[str, Any] = {
        "run_id": run_id,
        "stage": stage,
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "pipeline_version": artifact.pipeline_version,
        "created_at": artifact.created_at,
    }

    # Stage-specific summaries (no raw image bytes)
    if artifact_type == "ocr_evidence":
        snapshot["token_count"] = len(payload)
        snapshot["tokens"] = [
            {"id": t.stable_id, "text": t.text, "confidence": t.confidence,
             "bbox": [t.bbox.x1, t.bbox.y1, t.bbox.x2, t.bbox.y2]}
            for t in payload
        ]
    elif artifact_type == "geometry_evidence":
        snapshot["region_count"] = len(payload.get("regions", []))
        snapshot["line_count"]   = len(payload.get("lines", []))
        snapshot["regions"] = [
            {"id": r.stable_id, "bbox": [r.bbox.x1, r.bbox.y1, r.bbox.x2, r.bbox.y2],
             "confidence": r.geometry_confidence}
            for r in payload.get("regions", [])
        ]
    elif artifact_type == "alignment_evidence":
        snapshot["alignment_count"] = len(payload)
        snapshot["alignments"] = [
            {"id": a.stable_id, "type": a.alignment_type.value,
             "score": a.alignment_score, "token": a.source_evidence_id,
             "region": a.target_evidence_id}
            for a in payload
        ]
    elif artifact_type == "resolved_fields":
        snapshot["field_count"] = len(payload)
        snapshot["fields"] = [
            {"id": rf.field_id,
             "field_type": rf.field_type,
             "confidence": rf.confidence_breakdown.final_score,
             "ocr_tokens": rf.resolved_provenance.ocr_tokens,
             "alignment_edges": rf.resolved_provenance.alignment_edges}
            for rf in payload
        ]

    return snapshot
