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
from app.services.pipeline.perception_stage import PerceptionStage
from app.services.hitl.evidence_patcher import EvidencePatchStage
from app.services.topology.stage import TopologyStage
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
    orch.add_stage(PerceptionStage())
    orch.add_stage(EvidencePatchStage())
    orch.add_stage(TopologyStage())
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
    stages_to_clear = ["topology_evidence", "alignment_evidence", "resolved_fields"]
    if req.from_stage == "alignment":
        stages_to_clear = ["alignment_evidence", "resolved_fields"]
    elif req.from_stage == "alignment_fusion":
        stages_to_clear = ["resolved_fields"]
    elif req.from_stage == "topology_reconstruction":
        stages_to_clear = ["topology_evidence", "alignment_evidence", "resolved_fields"]

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
from app.services.schema.adapters.erpnext_adapter import export_to_erpnext

@router.get("/export/{run_id}")
async def export_run(run_id: str):
    """
    Exports resolved fields into Canonical Document, Form.io, and ERPNext formats.
    Uses zone topology to structure the output as parent-child hierarchy.
    """
    ctx, orch = _get_run(run_id)

    # ── Resolved Fields ──────────────────────────────────────────────────────
    rf_id = ctx.artifact_references.get("resolved_fields")
    if not rf_id:
        raise HTTPException(404, detail="Run has no resolved fields.")
    resolved_fields = orch.store.get(rf_id).payload

    # ── Semantic Zones (from topology) ───────────────────────────────────────
    zones = []
    topo_id = ctx.artifact_references.get("topology_evidence")
    if topo_id:
        topo_artifact = orch.store.get(topo_id)
        if topo_artifact:
            zones = getattr(topo_artifact.payload, "zones", []) or []

    # ── OCR Tokens (for label extraction) ────────────────────────────────────
    ocr_tokens = []
    ocr_id = ctx.artifact_references.get("ocr_evidence")
    if ocr_id:
        ocr_artifact = orch.store.get(ocr_id)
        if ocr_artifact:
            ocr_tokens = ocr_artifact.payload or []

    # ── Field Type Corrections from HITL Ledger ───────────────────────────────
    from app.services.hitl.operations_ledger import global_operations_ledger
    operations = global_operations_ledger.get_operations_for_run(run_id)
    corrections = {}
    for op in operations:
        if getattr(op, "operation_type", None) == "field_type_correction":
            # Using corrected_field_id if not present or field_id directly
            fid = getattr(op, "field_id", None)
            if fid:
                corrections[fid] = {
                    "corrected_type": getattr(op, "corrected_type", None),
                    "corrected_label": getattr(op, "corrected_label", ""),
                }

    # ── Build Canonical Document ──────────────────────────────────────────────
    canonical_doc = build_canonical_document(
        ctx.document_id,
        resolved_fields,
        zones=zones,
        ocr_tokens=ocr_tokens,
        field_type_corrections=corrections,
    )

    # ── Export Adapters ───────────────────────────────────────────────────────
    formio_schema   = export_to_formio(canonical_doc)
    erpnext_schema  = export_to_erpnext(canonical_doc)

    return {
        "canonical_document": canonical_doc.model_dump(),
        "formio_schema": formio_schema,
        "erpnext_schema": erpnext_schema,
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
        "coordinate_space": "coordinate_space_evidence",
        "shapes":     "shape_evidence",
        "topology":   "topology_evidence",
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
    elif artifact_type == "coordinate_space_evidence":
        snapshot["coordinate_space"] = payload
    elif artifact_type == "shape_evidence":
        snapshot["shape_count"] = len(payload)
        snapshot["shapes"] = [
            {
                "hu_moments": s.hu_moments,
                "area": s.area,
                "perimeter": s.perimeter,
                "aspect_ratio": s.aspect_ratio,
                "centroid": s.centroid
            }
            for s in payload
        ]
    elif artifact_type == "alignment_evidence":
        snapshot["alignment_count"] = len(payload)
        snapshot["alignments"] = [
            {"id": a.stable_id, "type": a.alignment_type.value,
             "score": a.alignment_score, "token": a.source_evidence_id,
             "region": a.target_evidence_id}
            for a in payload
        ]
    elif artifact_type == "topology_evidence":
        # Group cells by table_id to form table objects
        tables_by_id = {}
        for cell in payload.table_topologies:
            if cell.table_id not in tables_by_id:
                tables_by_id[cell.table_id] = []
            tables_by_id[cell.table_id].append(cell)

        tables_list = []
        for table_id, cells in tables_by_id.items():
            tx1 = min(c.bbox.x1 for c in cells)
            ty1 = min(c.bbox.y1 for c in cells)
            tx2 = max(c.bbox.x2 for c in cells)
            ty2 = max(c.bbox.y2 for c in cells)
            
            r_count = max(c.row_index + c.rowspan for c in cells)
            c_count = max(c.column_index + c.colspan for c in cells)

            tables_list.append({
                "table_id": table_id,
                "bbox": [tx1, ty1, tx2, ty2],
                "rows_count": r_count,
                "cols_count": c_count,
                "cells": [
                    {
                        "cell_id": c.cell_id,
                        "bbox": [c.bbox.x1, c.bbox.y1, c.bbox.x2, c.bbox.y2],
                        "row_index": c.row_index,
                        "column_index": c.column_index,
                        "rowspan": c.rowspan,
                        "colspan": c.colspan
                    }
                    for c in cells
                ]
            })

        snapshot["table_count"] = len(tables_list)
        snapshot["hierarchy_count"] = len(payload.region_hierarchy)
        snapshot["linked_checkboxes_count"] = len(payload.linked_checkboxes)
        snapshot["tables"] = tables_list
        snapshot["hierarchy"] = [
            {
                "stable_id": h.stable_id,
                "element_id": h.element_id,
                "element_type": h.element_type,
                "parent_id": h.parent_id,
                "children_ids": h.children_ids,
                "bbox": [h.bbox.x1, h.bbox.y1, h.bbox.x2, h.bbox.y2]
            }
            for h in payload.region_hierarchy
        ]
        snapshot["linked_checkboxes"] = payload.linked_checkboxes
        snapshot["zones"] = getattr(payload, "zones", [])
        if getattr(payload, "form_graph", None) is not None:
            if hasattr(payload.form_graph, "model_dump"):
                snapshot["form_graph"] = payload.form_graph.model_dump()
            else:
                snapshot["form_graph"] = payload.form_graph.dict()


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
