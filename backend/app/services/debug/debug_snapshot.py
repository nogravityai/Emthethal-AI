import uuid
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from app.models.schemas import BoundingBox

class DebugToken(BaseModel):
    token_id: str
    text: str
    bbox: BoundingBox

class DebugRegion(BaseModel):
    region_id: str
    bbox: BoundingBox

class DebugAssignment(BaseModel):
    token_ids: List[str]
    region_id: str
    score: float
    is_orphan_recovered: bool = False

class RejectedAssignment(BaseModel):
    token_ids: List[str]
    region_id: str
    reason: str
    score: float

class DebugAnchor(BaseModel):
    anchor_id: str
    bbox: BoundingBox
    type: str

class AssignmentDebugSnapshot(BaseModel):
    """
    Serializable, versioned, immutable snapshot of the assignment pipeline state.
    Serves as the basis for hitl-replay, QA baselines, and debug rendering.
    """
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    document_id: str
    page_id: int
    pipeline_version: str = "3.0.0"
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    tokens: List[DebugToken] = []
    regions: List[DebugRegion] = []
    assignments: List[DebugAssignment] = []
    orphan_tokens: List[DebugToken] = []
    rejected_assignments: List[RejectedAssignment] = []
    anchors: List[DebugAnchor] = []
    metadata: Dict[str, Any] = {}
