from typing import Optional, List
from pydantic import BaseModel, Field

from app.models.schemas import BoundingBox, CoordinateSpace
from app.services.ocr_adapter.models import CoordinateTransformTrace
from app.services.fusion.models import EvidenceProvenance
from app.services.pipeline.pipeline_models import generate_stable_id

class GeometryProvenance(EvidenceProvenance):
    """
    Extends base provenance with Geometry Drift Awareness fields.
    Records exactly how OpenCV derived this geometry.
    """
    opencv_version: str = "4.x"
    kernel_signature: str = "unknown"
    dpi_normalization: str = "identity"
    thresholding_profile: str = "default"

class DetectedLineEvidence(BaseModel):
    """Immutable evidence of a detected physical line."""
    stable_id: str
    geometry_confidence: float
    bbox: BoundingBox  # represents x1,y1 to x2,y2
    orientation: str   # 'horizontal' or 'vertical'
    coordinate_space: CoordinateSpace = CoordinateSpace.PAGE_PIXELS
    
    transform_trace: Optional[CoordinateTransformTrace] = None
    provenance: GeometryProvenance
    source_stage: str = "geometry_ingestion"
    pipeline_version: str = "3.0.0"

    @classmethod
    def create(cls, x1, y1, x2, y2, orientation, conf, prov, trace=None, page_w=1000, page_h=1000):
        s_id = generate_stable_id("line", x1, y1, x2, y2, orientation)
        # Slight epsilon padding to ensure x2 > x1 and y2 > y1 for horizontal/vertical lines
        bx1, by1, bx2, by2 = float(x1), float(y1), float(x2), float(y2)
        if bx2 <= bx1:
            bx2 = bx1 + 0.1
        if by2 <= by1:
            by2 = by1 + 0.1
        bbox = BoundingBox(x1=bx1, y1=by1, x2=bx2, y2=by2, coordinate_space=CoordinateSpace.PAGE_PIXELS, page_width=page_w, page_height=page_h)
        return cls(stable_id=s_id, geometry_confidence=conf, bbox=bbox, orientation=orientation, provenance=prov, transform_trace=trace)

class DetectedBoxEvidence(BaseModel):
    """Immutable evidence of a closed rectangular box (e.g. from findContours)."""
    stable_id: str
    geometry_confidence: float
    bbox: BoundingBox
    coordinate_space: CoordinateSpace = CoordinateSpace.PAGE_PIXELS
    
    transform_trace: Optional[CoordinateTransformTrace] = None
    provenance: GeometryProvenance
    source_stage: str = "geometry_ingestion"
    pipeline_version: str = "3.0.0"

    @classmethod
    def create(cls, x1, y1, x2, y2, conf, prov, trace=None, page_w=1000, page_h=1000):
        s_id = generate_stable_id("box", x1, y1, x2, y2)
        bbox = BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2, coordinate_space=CoordinateSpace.PAGE_PIXELS, page_width=page_w, page_height=page_h)
        return cls(stable_id=s_id, geometry_confidence=conf, bbox=bbox, provenance=prov, transform_trace=trace)

class SpatialRegionEvidence(BaseModel):
    """
    Immutable evidence of a region (often a 1:1 map to a DetectedBoxEvidence initially,
    but explicitly separated so it can act as an assignment candidate).
    """
    stable_id: str
    geometry_confidence: float
    bbox: BoundingBox
    derived_from_box: Optional[str] = None # Link to DetectedBoxEvidence ID
    coordinate_space: CoordinateSpace = CoordinateSpace.PAGE_PIXELS
    
    transform_trace: Optional[CoordinateTransformTrace] = None
    provenance: GeometryProvenance
    source_stage: str = "geometry_ingestion"
    pipeline_version: str = "3.0.0"

    # Semantic/Topology properties
    region_type: Optional[str] = "table"
    logical_row_id: Optional[str] = None
    logical_col_id: Optional[str] = None
    logical_cell_id: Optional[str] = None
    table_id: Optional[str] = None


    @classmethod
    def create_from_box(cls, box: DetectedBoxEvidence):
        s_id = generate_stable_id("region", box.stable_id)
        return cls(
            stable_id=s_id,
            geometry_confidence=box.geometry_confidence,
            bbox=box.bbox,
            derived_from_box=box.stable_id,
            provenance=box.provenance,
            transform_trace=box.transform_trace
        )
