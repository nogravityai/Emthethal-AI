"""
core/charts/models.py — Emthethal AI
====================================
Visual Coordinate models for mapping and identifying chart data.
"""

from datetime import datetime
import math
from typing import List, Tuple, Union, Optional
from pydantic import BaseModel, Field, model_validator

from app.models.schemas import BoundingBox, CoordinateSpace
from app.services.fusion.models import EvidenceProvenance
from app.core.contracts.evidence_contracts import ISpatialEvidence, ITemporalEvidence


class AxisCalibration(BaseModel):
    """
    Calibrates a single physical axis on a chart to map pixel values to numeric values.
    """
    min_pixel: float = Field(..., description="Starting pixel coordinate on the page")
    max_pixel: float = Field(..., description="Ending pixel coordinate on the page")
    min_value: float = Field(..., description="Real-world value at min_pixel")
    max_value: float = Field(..., description="Real-world value at max_pixel")
    scale_type: str = Field(default="linear", description="Scale type: 'linear' or 'log'")

    @model_validator(mode="after")
    def validate_calibration(self) -> "AxisCalibration":
        if math.isclose(self.min_pixel, self.max_pixel):
            raise ValueError("min_pixel and max_pixel cannot be identical")
        if math.isclose(self.min_value, self.max_value) and self.scale_type == "linear":
            raise ValueError("min_value and max_value cannot be identical for linear scale")
        return self


class ChartCoordinateSystem(BaseModel):
    """
    Represents the mapping coordinates for a specific 2D visual chart/graph.
    """
    stable_id: str = Field(..., description="Stable identifier of the chart region")
    bbox: BoundingBox = Field(..., description="Bounding box of the chart on the page")
    x_axis: AxisCalibration = Field(..., description="Calibration for the X axis")
    y_axis: AxisCalibration = Field(..., description="Calibration for the Y axis")
    page_number: int = Field(..., ge=0)

    def pixel_to_real(self, x: float, y: float) -> Tuple[float, float]:
        """
        Converts pixel coordinates to real-world coordinates.
        """
        # X-axis conversion
        if self.x_axis.scale_type == "linear":
            x_pct = (x - self.x_axis.min_pixel) / (self.x_axis.max_pixel - self.x_axis.min_pixel)
            x_val = self.x_axis.min_value + x_pct * (self.x_axis.max_value - self.x_axis.min_value)
        else:
            raise NotImplementedError(f"Scale type {self.x_axis.scale_type} not implemented")

        # Y-axis conversion
        if self.y_axis.scale_type == "linear":
            y_pct = (y - self.y_axis.min_pixel) / (self.y_axis.max_pixel - self.y_axis.min_pixel)
            y_val = self.y_axis.min_value + y_pct * (self.y_axis.max_value - self.y_axis.min_value)
        else:
            raise NotImplementedError(f"Scale type {self.y_axis.scale_type} not implemented")

        return x_val, y_val

    def real_to_pixel(self, x_val: float, y_val: float) -> Tuple[float, float]:
        """
        Converts real-world values back to page pixel coordinates.
        """
        # X-axis conversion
        if self.x_axis.scale_type == "linear":
            x_pct = (x_val - self.x_axis.min_value) / (self.x_axis.max_value - self.x_axis.min_value)
            x = self.x_axis.min_pixel + x_pct * (self.x_axis.max_pixel - self.x_axis.min_pixel)
        else:
            raise NotImplementedError(f"Scale type {self.x_axis.scale_type} not implemented")

        # Y-axis conversion
        if self.y_axis.scale_type == "linear":
            y_pct = (y_val - self.y_axis.min_value) / (self.y_axis.max_value - self.y_axis.min_value)
            y = self.y_axis.min_pixel + y_pct * (self.y_axis.max_pixel - self.y_axis.min_pixel)
        else:
            raise NotImplementedError(f"Scale type {self.y_axis.scale_type} not implemented")

        return x, y


class ShapeEmbedding(BaseModel):
    """
    Scale, translation, and rotation invariant descriptor of a contour shape.
    Uses Hu Moments under log transformation for stable geometric comparison.
    """
    hu_moments: List[float] = Field(
        ..., 
        description="7 scale and rotation invariant Hu moments",
        min_items=7,
        max_items=7
    )
    area: float = Field(..., description="Raw contour area")
    perimeter: float = Field(..., description="Raw contour perimeter")
    aspect_ratio: float = Field(..., description="Width/Height ratio")
    centroid: Tuple[float, float] = Field(..., description="Center of mass (x, y) on the page")

    def log_transform_moments(self) -> List[float]:
        """
        Applies log-transformation to make hu_moments comparable across magnitudes.
        `log_h_i = sign(h_i) * log10(|h_i|)` if h_i != 0 else 0.
        """
        transformed = []
        for h in self.hu_moments:
            if h == 0.0:
                transformed.append(0.0)
            else:
                sign = 1.0 if h > 0 else -1.0
                transformed.append(sign * math.log10(abs(h)))
        return transformed

    def match_similarity(self, other: "ShapeEmbedding") -> float:
        """
        Compares shape embeddings using OpenCV-compatible matching based on log-transformed Hu moments.
        Returns a score in range [0.0, 1.0] where 1.0 is exact match.
        """
        self_log = self.log_transform_moments()
        other_log = other.log_transform_moments()
        
        # Calculate sum of absolute reciprocal difference (normalized difference)
        diff_sum = 0.0
        for i in range(7):
            diff_sum += abs(self_log[i] - other_log[i])
            
        # Map difference sum to a similarity score [0, 1]
        # Low difference -> High similarity
        return 1.0 / (1.0 + diff_sum)


class TemporalPointEvidence(BaseModel):
    """
    Represents a specific physical point inside a chart.
    Implements ISpatialEvidence and ITemporalEvidence.
    """
    stable_id: str = Field(..., description="Stable identifier")
    bbox: BoundingBox = Field(..., description="Bounding box containing this point")
    page_number: int = Field(..., ge=0)
    coordinate_space: CoordinateSpace = Field(default=CoordinateSpace.PAGE_PIXELS)
    
    timestamp: Union[datetime, float] = Field(..., description="Time index value")
    value: float = Field(..., description="Calibrated numeric value from the chart")
    value_label: Optional[str] = Field(default=None, description="Label for this series/value")
    
    provenance: EvidenceProvenance = Field(..., description="Lineage details")
    shape_embedding: Optional[ShapeEmbedding] = Field(default=None, description="Geometric details")

    @model_validator(mode="after")
    def validate_spatial_and_temporal(self) -> "TemporalPointEvidence":
        # Enforce contract rules directly inside the schema
        if self.bbox.coordinate_space != self.coordinate_space:
            raise ValueError("BoundingBox coordinate space must match outer coordinate space")
        if isinstance(self.timestamp, float) and self.timestamp < 0:
            raise ValueError("Elapsed time float cannot be negative")
        return self

    # Enforce Python protocols
    def __check_protocols(self) -> None:
        _: ISpatialEvidence = self
        _: ITemporalEvidence = self
