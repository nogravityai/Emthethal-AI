import uuid
from typing import List, Optional
from pydantic import BaseModel, Field
from app.services.fusion.models import EvidenceProvenance

class AssignmentEvidence(BaseModel):
    """
    Immutable evidence representing the spatial grounding of tokens into regions.
    Assignment itself is Evidence, not absolute Truth.
    """
    evidence_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    token_ids: List[str]
    region_id: Optional[str]
    page_number: int
    
    # Probabilistic scoring layer
    assignment_score: float = 0.0
    overlap_ratio: float = 0.0
    iou_score: float = 0.0
    center_score: float = 0.0
    adjacency_score: float = 0.0
    anchor_consistency: float = 1.0
    reading_order_score: float = 1.0
    
    # State flags
    orphaned: bool = False
    rejected_by_anchor: bool = False
    
    # Provenance
    provenance: EvidenceProvenance
