from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field

from app.services.pipeline.pipeline_models import generate_stable_id
from app.services.fusion.models import EvidenceProvenance

class AlignmentType(str, Enum):
    TOKEN_INSIDE_REGION = "token_inside_region"
    TOKEN_TOUCHING_REGION = "token_touching_region"
    TOKEN_CROSSES_BOUNDARY = "token_crosses_boundary"

class OverlapMetrics(BaseModel):
    """Deterministic geometry metrics for an alignment candidate."""
    iou: float = 0.0                     # Intersection over Union
    intersection_area: float = 0.0
    token_coverage: float = 0.0          # % of token covered by region
    region_coverage: float = 0.0         # % of region covered by token
    centroid_distance: float = 0.0

class AlignmentEvidence(BaseModel):
    """
    Immutable record linking an OCR Token to a Spatial Region.
    Alignment DOES NOT decide which is truth — it only scores the relationship.
    The Fusion Engine decides what to believe later.
    """
    stable_id: str
    source_evidence_id: str      # OCRTokenEvidence.stable_id
    target_evidence_id: str      # SpatialRegionEvidence.stable_id
    alignment_type: AlignmentType
    alignment_score: float
    overlap_metrics: OverlapMetrics
    provenance: EvidenceProvenance
    rejection_reasons: List[str] = Field(default_factory=list)

    @classmethod
    def create(
        cls,
        source_id: str,
        target_id: str,
        alignment_type: AlignmentType,
        score: float,
        metrics: OverlapMetrics,
        rejection_reasons: List[str] = None
    ) -> "AlignmentEvidence":
        s_id = generate_stable_id("alignment", source_id, target_id, alignment_type.value)
        prov = EvidenceProvenance(
            source_module="alignment_engine",
            evidence_type="spatial_alignment",
            confidence_contribution=score,
            created_by_stage="cross_evidence_alignment",
            created_at_pipeline_step=3
        )
        return cls(
            stable_id=s_id,
            source_evidence_id=source_id,
            target_evidence_id=target_id,
            alignment_type=alignment_type,
            alignment_score=score,
            overlap_metrics=metrics,
            provenance=prov,
            rejection_reasons=rejection_reasons or []
        )
