"""
TASK-P3-12A — Human Operation Models

These models represent intentional interventions by a human operator.
They do not overwrite results; they act as patches to the Evidence Graph.
"""
from typing import List, Literal, Optional, Any, Dict
from pydantic import BaseModel, Field
from datetime import datetime, timezone
import uuid

from app.services.pipeline.pipeline_models import generate_stable_id


class HumanOperation(BaseModel):
    """Base class for all HITL intentional operations."""
    operation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    operator_id: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    target_evidence_ids: List[str]
    operation_type: str
    reason_code: str = "manual_correction"
    provenance_link: Optional[str] = None

    def get_stable_hash(self) -> str:
        return generate_stable_id(self.run_id, self.operator_id, self.operation_type, *self.target_evidence_ids)


class HumanLineApproval(HumanOperation):
    operation_type: Literal["line_approval"] = "line_approval"


class HumanLineRejection(HumanOperation):
    operation_type: Literal["line_rejection"] = "line_rejection"


class HumanRegionMerge(HumanOperation):
    operation_type: Literal["region_merge"] = "region_merge"
    source_regions: List[str]  # Region stable_ids to merge
    # target_evidence_ids will hold the new derived region stable_id


class HumanRegionSplit(HumanOperation):
    operation_type: Literal["region_split"] = "region_split"
    source_region: str
    split_coordinates: Dict[str, Any]  # Intent-based coordinates or relative splits


class HumanTokenReassignment(HumanOperation):
    operation_type: Literal["token_reassignment"] = "token_reassignment"
    token_id: str
    new_region_id: str


class HumanCheckboxCorrection(HumanOperation):
    operation_type: Literal["checkbox_correction"] = "checkbox_correction"
    region_id: str
    new_state: bool


class HumanRelabelCorrection(HumanOperation):
    operation_type: Literal["relabel"] = "relabel"
    region_id: str
    new_value: str


