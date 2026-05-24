import uuid
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from app.models.schemas import BoundingBox, CoordinateSpace
from app.services.fusion.models import EvidenceProvenance
from app.services.pipeline.pipeline_models import generate_stable_id

class CoordinateTransformTrace(BaseModel):
    """
    Documents exactly how coordinates were transformed.
    Critical for drift detection and bounding box auditing.
    """
    original_space: str
    target_space: str = CoordinateSpace.PAGE_PIXELS.value
    scale_x: float = 1.0
    scale_y: float = 1.0
    offset_x: float = 0.0
    offset_y: float = 0.0
    dpi_assumed: Optional[int] = None

class OCRTokenEvidence(BaseModel):
    """
    Strict evidence representation of an OCR token. 
    Not allowed to bypass the assignment engine.
    """
    stable_id: str
    text: str
    bbox: BoundingBox
    confidence: float
    source_engine: str  # e.g., 'paddleocr', 'easyocr', 'pdfplumber'
    engine_version: str = "unknown"
    adapter_version: str = "1.0.0"
    page_number: int
    coordinate_space: CoordinateSpace = CoordinateSpace.PAGE_PIXELS
    
    provenance: EvidenceProvenance
    transform_trace: Optional[CoordinateTransformTrace] = None

    # Semantic/Topology properties
    logical_row_id: Optional[str] = None
    logical_col_id: Optional[str] = None
    logical_cell_id: Optional[str] = None
    table_id: Optional[str] = None

    
    @classmethod
    def create(cls, text: str, bbox: BoundingBox, confidence: float, source_engine: str, page_number: int, trace: CoordinateTransformTrace = None, engine_version: str = "unknown") -> "OCRTokenEvidence":
        # Generate stable ID based on absolute content to prevent non-deterministic UUID jitter
        s_id = generate_stable_id(page_number, bbox.x1, bbox.y1, text, source_engine)
        
        prov = EvidenceProvenance(
            source_module="ocr_adapter",
            evidence_type="raw_token",
            confidence_contribution=confidence,
            created_by_stage="ocr_ingestion",
            created_at_pipeline_step=1
        )
        
        return cls(
            stable_id=s_id,
            text=text,
            bbox=bbox,
            confidence=confidence,
            source_engine=source_engine,
            engine_version=engine_version,
            page_number=page_number,
            coordinate_space=CoordinateSpace.PAGE_PIXELS,
            provenance=prov,
            transform_trace=trace
        )
