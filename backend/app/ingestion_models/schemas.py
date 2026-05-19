"""
models/schemas.py — Emthethal AI
Strict Pydantic V2 Contracts for the Document Intelligence Pipeline.

Every piece of data MUST pass through these models before hitting the Vector DB
or returning an API response. This is the absolute law of the system.
"""

from pydantic import BaseModel, Field, field_validator, model_validator
from typing import List, Optional, Dict, Any
from enum import Enum
from datetime import datetime


# ─── Enums ────────────────────────────────────────────────────────────────────

class DocumentStatus(str, Enum):
    """Validation gate outcome."""
    PASS = "pass"
    WARNING = "warning"
    HARD_STOP = "hard_stop"


class BlockType(str, Enum):
    """Supported structure block types."""
    TABLE = "table"
    FORM = "form"
    MIXED = "mixed"


class FileType(str, Enum):
    """Supported input file types."""
    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    DOC = "doc"
    IMAGE = "image"


# ─── Cell-Level Schema ────────────────────────────────────────────────────────

class ExtractedCell(BaseModel):
    """
    A single cell extracted from a table or form.
    - text: raw OCR / parsed text
    - value: normalized value (post-LLM)
    - confidence: OCR confidence [0.0 - 1.0]
    - bbox: bounding box [x1, y1, x2, y2] (mandatory for PDF)
    """
    text: str
    value: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    bbox: Optional[List[float]] = None  # [x1, y1, x2, y2]

    @field_validator("bbox")
    @classmethod
    def validate_bbox(cls, v: Optional[List[float]]) -> Optional[List[float]]:
        if v is not None:
            if len(v) != 4:
                raise ValueError("bbox must have exactly 4 coordinates: [x1, y1, x2, y2]")
            x1, y1, x2, y2 = v
            if x1 > x2 or y1 > y2:
                raise ValueError("Invalid bbox: x1 must be <= x2 and y1 must be <= y2")
        return v


# ─── Row-Level Schema ─────────────────────────────────────────────────────────

class TableRow(BaseModel):
    """A row of cells within a structure block."""
    cells: List[ExtractedCell]

    @field_validator("cells")
    @classmethod
    def validate_non_empty(cls, v: List[ExtractedCell]) -> List[ExtractedCell]:
        if not v:
            raise ValueError("TableRow must contain at least one cell")
        return v

    @property
    def avg_confidence(self) -> float:
        """Average confidence score across all cells in this row."""
        if not self.cells:
            return 0.0
        return sum(c.confidence for c in self.cells) / len(self.cells)

    def to_text(self) -> str:
        """Render row as pipe-delimited text for embedding."""
        return " | ".join(c.text for c in self.cells)


# ─── StructureBlock Schema ────────────────────────────────────────────────────

class StructureBlock(BaseModel):
    """
    A discrete structural unit extracted from a document.
    Could be a table, form, or mixed block.
    Each block carries its own confidence score.
    """
    type: str = Field(description="Block type: 'table', 'form', or 'mixed'")
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    rows: List[TableRow]
    headers: Optional[List[str]] = None  # Column headers if detected
    title: Optional[str] = None  # Block title if detected (e.g., "Sterilization Log")

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        allowed = {"table", "form", "mixed"}
        if v not in allowed:
            raise ValueError(f"Block type must be one of {allowed}, got '{v}'")
        return v

    @field_validator("rows")
    @classmethod
    def validate_rows_non_empty(cls, v: List[TableRow]) -> List[TableRow]:
        if not v:
            raise ValueError("StructureBlock must contain at least one row")
        return v

    @property
    def avg_confidence(self) -> float:
        """Average confidence across all rows."""
        if not self.rows:
            return 0.0
        return sum(r.avg_confidence for r in self.rows) / len(self.rows)

    @property
    def total_cells(self) -> int:
        return sum(len(r.cells) for r in self.rows)

    def to_text(self) -> str:
        """Render block as structured text for embedding."""
        lines = []
        if self.title:
            lines.append(f"[{self.type.upper()}] {self.title}")
        if self.headers:
            lines.append(" | ".join(self.headers))
            lines.append("-" * 40)
        for row in self.rows:
            lines.append(row.to_text())
        return "\n".join(lines)


# ─── Page Schema ──────────────────────────────────────────────────────────────

class PageOutput(BaseModel):
    """Represents a single page of extracted data."""
    page_number: int = Field(ge=1)
    blocks: List[StructureBlock]
    raw_text: Optional[str] = None  # Fallback text if no structures detected

    @property
    def avg_confidence(self) -> float:
        if not self.blocks:
            return 0.0
        return sum(b.avg_confidence for b in self.blocks) / len(self.blocks)


# ─── Document Output (Top-Level Contract) ─────────────────────────────────────

class DocumentOutput(BaseModel):
    """
    THE master output schema. Every document MUST be validated through this
    before entering the Vector DB or being returned to the API.
    """
    document_type: str  # "medical_form", "compliance_report", "inspection_log", etc.
    source_filename: str
    file_type: str  # "pdf", "docx", "xlsx"
    pages: List[PageOutput]
    status: str = Field(default="pass")  # "pass", "warning", "hard_stop"
    quarantine_flag: bool = Field(default=False)
    avni_mapping_ready: bool = Field(default=True)
    processing_metadata: Optional[Dict[str, Any]] = None
    extracted_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        allowed = {"pass", "warning", "hard_stop"}
        if v not in allowed:
            raise ValueError(f"Status must be one of {allowed}")
        return v

    @property
    def total_blocks(self) -> int:
        return sum(len(p.blocks) for p in self.pages)

    @property
    def total_rows(self) -> int:
        return sum(len(b.rows) for p in self.pages for b in p.blocks)

    @property
    def avg_confidence(self) -> float:
        """Global confidence across all pages."""
        all_blocks = [b for p in self.pages for b in p.blocks]
        if not all_blocks:
            return 0.0
        return sum(b.avg_confidence for b in all_blocks) / len(all_blocks)


# ─── Quarantine Gate Config ───────────────────────────────────────────────────

class QuarantineConfig(BaseModel):
    """Configuration for the validation gate before Vector DB insertion."""
    min_avg_confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    require_bbox_for_pdf: bool = Field(default=True)
    min_blocks_per_page: int = Field(default=0, ge=0)
    max_empty_cell_ratio: float = Field(default=0.5, ge=0.0, le=1.0)


# ─── Quarantine Result ────────────────────────────────────────────────────────

class QuarantineResult(BaseModel):
    """Output of the quarantine validation gate."""
    passed: bool
    status: str  # "pass", "warning", "hard_stop"
    violations: List[str] = Field(default_factory=list)
    avg_confidence: float
    quarantine_flag: bool


# ─── Ingestion API Schemas ────────────────────────────────────────────────────

class IngestionRequest(BaseModel):
    """Metadata attached to file upload for ingestion."""
    department: str = Field(default="General", description="Department name")
    device_name: str = Field(default="General", description="Device or asset name")
    form_type: str = Field(default="General", description="Form type classification")
    document_type: str = Field(default="medical_form", description="Document classification")


class IngestionResponse(BaseModel):
    """Response returned from the /api/v1/ingest endpoint."""
    status: str
    filename: str
    file_type: str
    document_output: Optional[DocumentOutput] = None
    quarantine_result: Optional[QuarantineResult] = None
    chunks_stored: int = 0
    processing_time_ms: float = 0.0
    errors: List[str] = Field(default_factory=list)
