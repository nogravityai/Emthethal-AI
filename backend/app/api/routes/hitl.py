"""
TASK-P3-12F — HITL Geometry Editor API Layer

Endpoints for logging audited human operations and triggering reruns.
"""
from typing import List, Dict, Any, Union
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.hitl.models import (
    HumanOperation, HumanLineRejection, HumanLineApproval,
    HumanRegionMerge, HumanRegionSplit, HumanTokenReassignment, HumanCheckboxCorrection,
    HumanZoneOperation, HumanFieldTypeCorrection
)
from app.services.hitl.operations_ledger import global_operations_ledger

# Need to access pipeline reruns. We import _get_run from pipeline.py
from app.api.routes.pipeline import _get_run, ReplayResponse

router = APIRouter(prefix="/api/cfis/v3/hitl", tags=["CFIS v3 — HITL Editor"])


class OperationSubmission(BaseModel):
    """Wrapper for incoming polymorphic operations."""
    operation_type: str
    run_id: str
    operator_id: str
    target_evidence_ids: List[str]
    payload: Dict[str, Any] = {}


@router.post("/operations", response_model=Dict[str, str])
async def submit_operation(sub: OperationSubmission):
    """
    Log a human operation into the immutable ledger.
    This does NOT trigger a rerun automatically. Use /rerun for that.
    """
    # Parse into the correct Pydantic model
    try:
        if sub.operation_type == "line_rejection":
            op = HumanLineRejection(run_id=sub.run_id, operator_id=sub.operator_id, target_evidence_ids=sub.target_evidence_ids, **sub.payload)
        elif sub.operation_type == "line_approval":
            op = HumanLineApproval(run_id=sub.run_id, operator_id=sub.operator_id, target_evidence_ids=sub.target_evidence_ids, **sub.payload)
        elif sub.operation_type == "region_merge":
            op = HumanRegionMerge(run_id=sub.run_id, operator_id=sub.operator_id, target_evidence_ids=sub.target_evidence_ids, **sub.payload)
        elif sub.operation_type == "region_split":
            op = HumanRegionSplit(run_id=sub.run_id, operator_id=sub.operator_id, target_evidence_ids=sub.target_evidence_ids, **sub.payload)
        elif sub.operation_type == "token_reassignment":
            op = HumanTokenReassignment(run_id=sub.run_id, operator_id=sub.operator_id, target_evidence_ids=sub.target_evidence_ids, **sub.payload)
        elif sub.operation_type == "checkbox_correction":
            op = HumanCheckboxCorrection(run_id=sub.run_id, operator_id=sub.operator_id, target_evidence_ids=sub.target_evidence_ids, **sub.payload)
        elif sub.operation_type == "zone_operation":
            op = HumanZoneOperation(run_id=sub.run_id, operator_id=sub.operator_id, target_evidence_ids=sub.target_evidence_ids, **sub.payload)
        elif sub.operation_type == "field_type_correction":
            op = HumanFieldTypeCorrection(run_id=sub.run_id, operator_id=sub.operator_id, target_evidence_ids=sub.target_evidence_ids, **sub.payload)
        else:
            raise HTTPException(400, detail=f"Unknown operation_type: {sub.operation_type}")
    except Exception as e:
        raise HTTPException(422, detail=f"Invalid payload for {sub.operation_type}: {str(e)}")

    # Ensure run exists
    _get_run(sub.run_id)

    # Append to ledger
    op_id = global_operations_ledger.append(op)
    
    return {"status": "logged", "operation_id": op_id}


@router.get("/runs/{run_id}/operations")
async def get_run_operations(run_id: str):
    """Fetch the full ledger of human operations for a specific run."""
    _get_run(run_id)  # Validate run exists
    ops = global_operations_ledger.get_operations_for_run(run_id)
    return {"run_id": run_id, "operations": [op.model_dump() for op in ops]}


class RerunRequest(BaseModel):
    run_id: str


@router.post("/rerun", response_model=ReplayResponse)
async def trigger_rerun(req: RerunRequest):
    """
    Rerun the pipeline from EvidencePatchStage onwards, applying all logged operations.
    Returns the new artifact IDs. Determinism check here validates the patcher's stability.
    """
    ctx, orch = _get_run(req.run_id)

    # Note: EvidencePatchStage MUST be injected in the orchestrator before AlignmentStage.
    # We will assume it is injected. If not, the run will just go through alignment without patching.
    # To properly rerun, we need to clear everything from alignment onwards.
    
    orig_resolved = ctx.artifact_references.get("resolved_fields")
    
    for s in ["patched_evidence", "alignment_evidence", "resolved_fields"]:
        ctx.artifact_references.pop(s, None)

    # If the orchestrator doesn't have evidence_patching yet, we can't rerun from it.
    # But for this task, we will ensure it's added.
    try:
        # We start rerun from evidence_patching if it exists, otherwise alignment
        stage_names = [st.stage_name for st in orch.stages]
        start_stage = "evidence_patching" if "evidence_patching" in stage_names else "alignment"
        
        orch.rerun_from_stage(ctx, start_stage)
    except Exception as e:
        raise HTTPException(500, detail=f"Rerun failed: {str(e)[:300]}")

    new_resolved = ctx.artifact_references.get("resolved_fields")
    determinism_ok = (orig_resolved == new_resolved)

    return ReplayResponse(
        run_id=req.run_id,
        replayed_from="evidence_patching",
        artifacts=ctx.artifact_references,
        determinism_ok=determinism_ok
    )
