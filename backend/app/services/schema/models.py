"""
TASK-P3-14A — Canonical Schema Models  [CFIS v5.2 — Zone-Aware]

Business-safe representation of the final document.
Completely isolated from Evidence, Graphs, or CV internals.

v2.0.0 additions:
  - FieldType enum with 14 semantic types
  - CanonicalField.bbox      — pixel coordinates [x1, y1, x2, y2]
  - CanonicalField.zone_id   — parent zone reference
  - CanonicalField.include_in_form — exclude headers/footers from export
  - CanonicalSection.zone_type / include_in_form
  - CanonicalDocument.title  — populated from form_title zone
"""
from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
import uuid


# ── Field Type Enum ────────────────────────────────────────────────────────────
class FieldType(str, Enum):
    TEXT      = "text"
    NUMBER    = "number"
    DATE      = "date"
    CHECKBOX  = "checkbox"
    RADIO     = "radio"
    DROPDOWN  = "dropdown"
    NAME      = "name"
    PHONE     = "phone"
    EMAIL     = "email"
    SIGNATURE = "signature"
    HEADER    = "header"      # Section-header label — excluded from export
    FORM_TITLE = "form_title" # Top-level form name zone
    TABLE     = "table"
    UNKNOWN   = "unknown"


# ── Field Models ───────────────────────────────────────────────────────────────
class CanonicalField(BaseModel):
    field_id: str
    field_name: str
    value: Any
    confidence_score: float
    field_type: str = FieldType.TEXT          # use FieldType enum value
    provenance_ref: str                       # → ResolvedField stable_id
    bbox: Optional[List[int]] = None          # [x1, y1, x2, y2] in page pixels
    zone_id: Optional[str] = None            # parent SemanticZone ID
    include_in_form: bool = True             # False → excluded from all exports


class CanonicalCheckbox(CanonicalField):
    field_type: str = FieldType.CHECKBOX
    value: bool


class CanonicalSignature(CanonicalField):
    field_type: str = FieldType.SIGNATURE
    is_signed: bool


# ── Table Models ───────────────────────────────────────────────────────────────
class CanonicalTableColumn(BaseModel):
    column_id: str
    header: str


class CanonicalTableRow(BaseModel):
    row_id: str
    cells: Dict[str, CanonicalField]


class CanonicalTable(BaseModel):
    table_id: str
    name: str
    columns: List[CanonicalTableColumn]
    rows: List[CanonicalTableRow]


# ── Section / Page / Document ──────────────────────────────────────────────────
class CanonicalSection(BaseModel):
    section_id: str
    title: str
    zone_type: str = "unknown"               # mirrors SemanticZone.zone_type
    include_in_form: bool = True             # False → section skipped in export
    fields: List[CanonicalField] = Field(default_factory=list)
    tables: List[CanonicalTable] = Field(default_factory=list)


class CanonicalPage(BaseModel):
    page_number: int
    sections: List[CanonicalSection] = Field(default_factory=list)


class CanonicalDocument(BaseModel):
    schema_version: str = "2.0.0"
    document_id: str
    title: str = "Untitled Document"        # populated from form_title zone
    pages: List[CanonicalPage] = Field(default_factory=list)
