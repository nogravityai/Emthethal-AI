# ============================================================
# CFIS Canonical Schema v2 — Pydantic v2 API
# ONE file. ONE source of truth. Edit in place, never duplicate.
# Location: backend/app/models/schemas.py
#
# Layer 0: Coordinates
# Layer 1: Canonical Token (native OR ocr — unified)
# Layer 2: Layout Cell (geometry IR)
# Layer 3: Form Field (semantic IR)
# Layer 4: Document Output (delivery contract)
# ============================================================

from __future__ import annotations
from typing import Optional, List, Literal, Dict, Any, Tuple
from pydantic import BaseModel, Field, field_validator, model_validator
from datetime import datetime, timezone
from enum import Enum
import hashlib
import uuid

# ══════════════════════════════════════════════════════════════
# LAYER 0: COORDINATE SYSTEM
#
# INVARIANT (R17, R20):
#   normalized.x = pixel.x / original_page_width
#   normalized.y = pixel.y / original_page_height
#   Always relative to ORIGINAL, UNCROPPED page.
#
# page_pixels : raw from OCR/pdf2image OR native PDF at DPI=200
# normalized  : 0.0–1.0, page-relative, used for frontend ONLY
# pdf_points  : 72 DPI PDF units (native pdfplumber extraction)
# ══════════════════════════════════════════════════════════════


class CoordinateSpace(str, Enum):
    PAGE_PIXELS = "page_pixels"
    NORMALIZED = "normalized"
    PDF_POINTS = "pdf_points"


Language = Literal["ar", "en", "ar_en"]


class BoundingBox(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float
    coordinate_space: CoordinateSpace = CoordinateSpace.PAGE_PIXELS
    page_width: int    # original page width in pixels — ALWAYS required
    page_height: int   # original page height in pixels — ALWAYS required

    @field_validator("x2")
    @classmethod
    def x2_greater_than_x1(cls, v: float, info) -> float:
        x1 = info.data.get("x1")
        if x1 is not None and v <= x1:
            raise ValueError(f"x2 ({v}) must be > x1 ({x1})")
        return v

    @field_validator("y2")
    @classmethod
    def y2_greater_than_y1(cls, v: float, info) -> float:
        y1 = info.data.get("y1")
        if y1 is not None and v <= y1:
            raise ValueError(f"y2 ({v}) must be > y1 ({y1})")
        return v

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def center(self) -> Tuple[float, float]:
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)

    def to_list(self) -> List[float]:
        return [self.x1, self.y1, self.x2, self.y2]

    def to_normalized(self) -> "BoundingBox":
        """Convert page_pixels or pdf_points → normalized (0.0–1.0). Frontend use only."""
        if self.coordinate_space == CoordinateSpace.NORMALIZED:
            return self
        return BoundingBox(
            x1=self.x1 / self.page_width,
            y1=self.y1 / self.page_height,
            x2=self.x2 / self.page_width,
            y2=self.y2 / self.page_height,
            coordinate_space=CoordinateSpace.NORMALIZED,
            page_width=self.page_width,
            page_height=self.page_height,
        )

    def to_page_pixels(self) -> "BoundingBox":
        """Convert normalized → page_pixels."""
        if self.coordinate_space == CoordinateSpace.PAGE_PIXELS:
            return self
        if self.coordinate_space != CoordinateSpace.NORMALIZED:
            raise ValueError(f"Cannot convert from space: {self.coordinate_space}")
        return BoundingBox(
            x1=self.x1 * self.page_width,
            y1=self.y1 * self.page_height,
            x2=self.x2 * self.page_width,
            y2=self.y2 * self.page_height,
            coordinate_space=CoordinateSpace.PAGE_PIXELS,
            page_width=self.page_width,
            page_height=self.page_height,
        )

    def iou(self, other: "BoundingBox") -> float:
        """Intersection over Union. Both boxes must be in same coordinate space."""
        if self.coordinate_space != other.coordinate_space:
            raise ValueError("Cannot compute IoU across different coordinate spaces")
        ix1 = max(self.x1, other.x1)
        iy1 = max(self.y1, other.y1)
        ix2 = min(self.x2, other.x2)
        iy2 = min(self.y2, other.y2)
        if ix2 <= ix1 or iy2 <= iy1:
            return 0.0
        inter = (ix2 - ix1) * (iy2 - iy1)
        union = self.area + other.area - inter
        return inter / union if union > 0 else 0.0


# ══════════════════════════════════════════════════════════════
# LAYER 1: CANONICAL TOKEN
#
# Unified token from either native PDF extraction OR OCR.
# Immutable after creation. Never enrich here.
# R19: ocr_raw_text ≠ semantic_label (kept strictly separate)
# ══════════════════════════════════════════════════════════════


class ExtractionSource(str, Enum):
    NATIVE = "native"   # pdfplumber / PyMuPDF text layer
    OCR = "ocr"         # PaddleOCR on rasterized page image


class CanonicalToken(BaseModel):
    """
    A single text token from native PDF text layer OR OCR.
    Coordinates always in PAGE_PIXELS (R17, R20).
    Sorted by (page_number, bbox.y1, bbox.x1) before clustering (R13).
    """
    ocr_raw_text: str                           # R19: raw extraction, NEVER semantic_label
    bbox: BoundingBox                           # PAGE_PIXELS at creation
    confidence: float = Field(ge=0.0, le=1.0)
    page_number: int = Field(ge=0)
    source: ExtractionSource = ExtractionSource.OCR
    angle_corrected: bool = False
    extraction_language: str = "native"

    # Semantic/Topology properties
    logical_row_id: Optional[str] = None
    logical_col_id: Optional[str] = None
    logical_cell_id: Optional[str] = None
    table_id: Optional[str] = None



# ══════════════════════════════════════════════════════════════
# LAYER 1.5: LAYOUT PROPOSAL
#
# Output from PP-StructureV3 — proposals ONLY.
# R18: NOT canonical truth — always normalize + validate.
# ══════════════════════════════════════════════════════════════


class LayoutProposal(BaseModel):
    """
    Layout proposals from PP-StructureV3.
    normalized = False until normalize_layout_proposal() is called.
    """
    page_number: int
    table_regions: List[BoundingBox] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    normalized: bool = False


# ══════════════════════════════════════════════════════════════
# LAYER 2: LAYOUT CELL (Geometry IR)
# ══════════════════════════════════════════════════════════════


class LayoutCell(BaseModel):
    """
    A geometric cell from DBSCAN clustering of CanonicalTokens.
    bbox is always in PAGE_PIXELS space.
    """
    cell_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    merged_text: str
    bbox: BoundingBox                  # PAGE_PIXELS
    row_index: int = Field(ge=0)
    column_index: int = Field(ge=0)
    page_number: int = Field(ge=0)
    token_count: int = Field(ge=1)
    avg_confidence: float = Field(ge=0.0, le=1.0)
    source: ExtractionSource = ExtractionSource.OCR

class TableTopologyEvidence(BaseModel):
    """
    Logical grid coordinates for a cell in a table.
    Resolved during topology reconstruction.
    """
    stable_id: str
    page_number: int = Field(ge=0)
    table_id: str
    row_index: int = Field(ge=0)
    column_index: int = Field(ge=0)
    rowspan: int = Field(ge=1, default=1)
    colspan: int = Field(ge=1, default=1)
    cell_id: str
    bbox: BoundingBox
    coordinate_space: CoordinateSpace = CoordinateSpace.PAGE_PIXELS


class RegionHierarchyEvidence(BaseModel):
    """
    Hierarchical structural relationships of document layout.
    page -> section -> table -> row -> cell
    """
    stable_id: str
    page_number: int = Field(ge=0)
    element_id: str
    element_type: str  # 'page', 'section', 'table', 'row', 'cell'
    parent_id: Optional[str] = None
    children_ids: List[str] = Field(default_factory=list)
    bbox: BoundingBox
    coordinate_space: CoordinateSpace = CoordinateSpace.PAGE_PIXELS


# ══════════════════════════════════════════════════════════════

# LAYER 3: FORM FIELD (Semantic IR)
#
# bbox MUST be NORMALIZED (0–1) — enforced by validator.
# R17: Coordinates are page-relative normalized values.
# R19: semantic_label is NOT ocr_raw_text.
# ══════════════════════════════════════════════════════════════


VALID_WIDGET_TYPES = {
    "text", "number", "radio", "select", "date", "datetime",
    "textarea", "checkbox", "repeating_rows", "signature",
    "nested_group", "hierarchical_table", "file", "unknown",
}


class FormField(BaseModel):
    """
    Semantic form field. bbox MUST be in NORMALIZED coordinate space.
    semantic_label is independent of ocr_raw_text (R19).
    """
    field_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    cell_id: str
    semantic_label: str
    semantic_label_ar: Optional[str] = None
    semantic_label_en: Optional[str] = None
    bbox: BoundingBox                  # MUST be NORMALIZED — enforced below
    row_index: int = Field(ge=0)
    column_index: int = Field(ge=0)
    page_number: int = Field(ge=0)
    language: str = "ar"
    is_rtl: bool = True
    runtime_widget: str = "text"
    options: Optional[List[str]] = None
    options_ar: Optional[List[str]] = None
    validation: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    needs_qa: bool = False
    human_corrected: bool = False
    kpi_code: Optional[str] = None
    source: ExtractionSource = ExtractionSource.OCR
    note: Optional[str] = None

    @field_validator("bbox")
    @classmethod
    def bbox_must_be_normalized(cls, v: BoundingBox) -> BoundingBox:
        if v.coordinate_space != CoordinateSpace.NORMALIZED:
            raise ValueError(
                f"FormField.bbox must be NORMALIZED, got {v.coordinate_space}. "
                "Call bbox.to_normalized() before creating a FormField."
            )
        return v

    @field_validator("runtime_widget")
    @classmethod
    def validate_widget_type(cls, v: str) -> str:
        return v if v in VALID_WIDGET_TYPES else "text"


# ══════════════════════════════════════════════════════════════
# LAYER 4: DOCUMENT OUTPUT (Delivery Contract)
# ══════════════════════════════════════════════════════════════


class PageDimension(BaseModel):
    """Original page dimensions. Used for coordinate normalization."""
    page_number: int
    width_px: int
    height_px: int
    width_pts: Optional[float] = None
    height_pts: Optional[float] = None
    has_native_text: bool = False


class TemplateFingerprint(BaseModel):
    """
    Structural fingerprint for template matching.
    eps values ALWAYS dynamic — derived from document statistics. (R4)
    """
    layout_hash: str
    page_count: int
    avg_confidence: float
    col_count: int
    row_count: int
    median_row_height: float
    median_col_gap: float
    computed_eps_y: float
    computed_eps_x: float
    primary_language: str = "ar"
    extraction_mode: str = "hybrid"
    total_tokens: int = 0

    @classmethod
    def compute(
        cls,
        page_count: int,
        avg_confidence: float,
        col_count: int,
        median_row_height: float,
        median_col_gap: float,
        total_tokens: int = 0,
        primary_language: str = "ar",
        row_count: int = 0,
        extraction_mode: str = "hybrid",
    ) -> "TemplateFingerprint":
        """
        Compute fingerprint from document geometry.
        eps ALWAYS derived dynamically — NEVER hardcoded. (R4)
        Hash uses structural geometry only — NOT ephemeral field_ids.
        """
        computed_eps_y = max(8.0, median_row_height * 0.65)
        computed_eps_x = max(10.0, median_col_gap * 0.55)

        hash_input = (
            f"{page_count}:{col_count}:{row_count}:"
            f"{round(median_row_height, 1)}:{round(median_col_gap, 1)}:"
            f"{primary_language}"
        )
        layout_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:16]

        return cls(
            layout_hash=layout_hash,
            page_count=page_count,
            avg_confidence=avg_confidence,
            col_count=col_count,
            row_count=row_count,
            median_row_height=median_row_height,
            median_col_gap=median_col_gap,
            computed_eps_y=computed_eps_y,
            computed_eps_x=computed_eps_x,
            primary_language=primary_language,
            extraction_mode=extraction_mode,
            total_tokens=total_tokens,
        )


class QACorrection(BaseModel):
    """Human correction applied to a FormField during QA review."""
    correction_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    document_id: str
    field_id: str
    cell_id: str
    layout_hash: str
    row_index: int
    column_index: int
    page_number: int
    corrected_label: Optional[str] = None
    corrected_widget: Optional[str] = None
    corrected_bbox: Optional[BoundingBox] = None
    note: Optional[str] = None
    corrected_by: str = "anonymous"
    corrected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("corrected_bbox")
    @classmethod
    def corrected_bbox_must_be_normalized(cls, v: Optional[BoundingBox]) -> Optional[BoundingBox]:
        if v is not None and v.coordinate_space != CoordinateSpace.NORMALIZED:
            raise ValueError("corrected_bbox must be NORMALIZED")
        return v


class DocumentOutput(BaseModel):
    """
    Master delivery contract. Persisted to PostgreSQL.
    All FormField bboxes in NORMALIZED space.
    failed_pages populated per R10 (page-level fault isolation).
    """
    document_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_file: str
    fingerprint: TemplateFingerprint
    primary_language: str = "ar"
    total_pages: int = Field(ge=0)
    qa_status: str = "pending"
    qa_issues_count: int = 0
    fields: List[FormField] = Field(default_factory=list)
    page_dimensions: List[PageDimension] = Field(default_factory=list)
    failed_pages: List[int] = Field(default_factory=list)
    processing_warnings: List[str] = Field(default_factory=list)
    extraction_stats: Dict[str, Any] = Field(default_factory=dict)
    approved_at: Optional[datetime] = None
    approved_by: Optional[str] = None
    processed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("qa_status")
    @classmethod
    def validate_qa_status(cls, v: str) -> str:
        allowed = {"pending", "in_review", "approved", "rejected"}
        if v not in allowed:
            raise ValueError(f"qa_status must be one of {allowed}")
        return v
