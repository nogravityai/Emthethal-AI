from __future__ import annotations
import uuid
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from app.models.schemas import BoundingBox

class ConfidenceBreakdown(BaseModel):
    """Explainable confidence components."""
    geometry_score: float = 0.0
    assignment_score: float = 0.0
    text_score: float = 0.0
    anchor_penalty: float = 0.0
    conflict_penalty: float = 0.0
    human_override_score: float = 0.0
    
    @property
    def final_score(self) -> float:
        base = (self.geometry_score * 0.4) + (self.assignment_score * 0.4) + (self.text_score * 0.2)
        penalty = self.anchor_penalty + self.conflict_penalty
        return max(0.0, min(1.0, base - penalty + self.human_override_score))

class EvidenceProvenance(BaseModel):
    """
    Tracks exactly WHY a hypothesis was formed and WHAT evidence supports it.
    Immutable record of decision making for auditing and HITL corrections.
    """
    source_module: str  # e.g., "visual_geometry", "text_clustering", "hitl_correction"
    evidence_type: str  # e.g., "visual_line_intersection", "dbscan_cluster", "user_override"
    confidence_contribution: float = 0.0
    reference_ids: List[str] = Field(default_factory=list) # IDs of CanonicalTokens, VisualLines, etc.
    metadata: Dict[str, Any] = Field(default_factory=dict) # E.g., overlap ratio, distance
    
    # Temporal Provenance
    created_by_stage: str = "initial"
    created_at_pipeline_step: int = 0
    derived_from_evidence: List[str] = Field(default_factory=list)

class HumanCorrectionEvidence(BaseModel):
    """
    Human corrections are just another type of evidence, injecting absolute confidence
    into the graph rather than mutating state directly.
    """
    correction_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    target_evidence_id: str
    action_type: str # "approve", "reject", "merge", "relabel"
    correction_data: Dict[str, Any]
    provenance: EvidenceProvenance

class LayoutHypothesis(BaseModel):
    """
    A candidate spatial region or structural element. NOT a final truth.
    All subsystems (Geometry, Text Clustering) MUST yield this.
    """
    hypothesis_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    hypothesis_type: str  # e.g., "table_cell", "checkbox", "section_header", "text_block"
    bbox: BoundingBox
    confidence_breakdown: ConfidenceBreakdown = Field(default_factory=ConfidenceBreakdown)
    provenance: List[EvidenceProvenance] = Field(default_factory=list)
    text_content: Optional[str] = None
    page_number: int

    # Note: Immutable artifact design. If HITL or Fusion modifies this, 
    # a NEW hypothesis is created linking back via provenance.

class ResolvedFieldProvenance(BaseModel):
    """
    TASK-P3-09D — Full audit trail for a resolved field.
    Every ID is a stable, deterministic hash that can be replayed.
    """
    ocr_tokens: List[str] = Field(default_factory=list)       # OCRTokenEvidence stable_ids
    alignment_edges: List[str] = Field(default_factory=list)  # AlignmentEvidence stable_ids
    geometry_regions: List[str] = Field(default_factory=list) # SpatialRegionEvidence stable_ids
    human_operations: List[str] = Field(default_factory=list) # HumanCorrectionEvidence ids

class ResolvedField(BaseModel):
    """
    The final, deterministic truth after Fusion Engine has resolved all conflicts.
    This is what gets exported to the Canonical Schema.
    """
    field_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    field_type: str
    bbox: Optional[BoundingBox] = None
    value: Optional[Any] = None
    confidence_breakdown: ConfidenceBreakdown
    supporting_hypotheses: List[str] = Field(default_factory=list)  # deprecated — kept for migration compat
    resolved_provenance: ResolvedFieldProvenance = Field(default_factory=ResolvedFieldProvenance)
    page_number: int
