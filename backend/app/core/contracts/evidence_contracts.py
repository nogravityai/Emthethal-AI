"""
core/contracts/evidence_contracts.py — Emthethal AI
===================================================
Structural contracts and protocols for the Visual Coordinate Layer.
"""

from datetime import datetime, timezone
from typing import Protocol, runtime_checkable, Union, Dict, Any
from pydantic import BaseModel, Field, model_validator

from app.models.schemas import BoundingBox, CoordinateSpace
from app.services.fusion.models import EvidenceProvenance


@runtime_checkable
class ISpatialEvidence(Protocol):
    """
    Protocol contract for any spatial layout evidence.
    """
    stable_id: str
    bbox: BoundingBox
    page_number: int
    coordinate_space: CoordinateSpace


@runtime_checkable
class ITemporalEvidence(Protocol):
    """
    Protocol contract for time-series or sequence-based evidence.
    """
    stable_id: str
    timestamp: Union[datetime, float]  # Timestamp or elapsed seconds
    provenance: EvidenceProvenance


class SpatialEvidenceContract(BaseModel):
    """
    Pydantic schema enforcing ISpatialEvidence validation and serialization.
    """
    stable_id: str = Field(..., description="Deterministic stable ID representing this evidence")
    bbox: BoundingBox = Field(..., description="Bounding box region")
    page_number: int = Field(..., ge=0, description="0-indexed page number")
    coordinate_space: CoordinateSpace = Field(
        default=CoordinateSpace.PAGE_PIXELS,
        description="Active coordinate space of this spatial evidence"
    )

    @model_validator(mode="after")
    def validate_spatial_consistency(self) -> "SpatialEvidenceContract":
        """Ensure coordinate space constraints are met."""
        if self.bbox.coordinate_space != self.coordinate_space:
            raise ValueError(
                f"Mismatch in coordinate space: outer is {self.coordinate_space}, "
                f"but bbox has {self.bbox.coordinate_space}"
            )
        return self


class TemporalEvidenceContract(BaseModel):
    """
    Pydantic schema enforcing ITemporalEvidence validation and serialization.
    """
    stable_id: str = Field(..., description="Deterministic stable ID representing this evidence")
    timestamp: Union[datetime, float] = Field(
        ...,
        description="ISO datetime or elapsed time float (seconds) for temporal mapping"
    )
    provenance: EvidenceProvenance = Field(..., description="Immutable lineage trail")

    @model_validator(mode="after")
    def validate_temporal_bounds(self) -> "TemporalEvidenceContract":
        """Enforce basic temporal bounds."""
        if isinstance(self.timestamp, float) and self.timestamp < 0:
            raise ValueError("Temporal elapsed time float cannot be negative")
        return self
