"""
TASK-P3-14A — Canonical Schema Models

Business-safe representation of the final document.
Completely isolated from Evidence, Graphs, or CV internals.
"""
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
import uuid

class CanonicalField(BaseModel):
    field_id: str
    field_name: str
    value: Any
    confidence_score: float
    field_type: str = "text" # text, checkbox, signature, etc.
    provenance_ref: str # Link back to ResolvedField stable_id for auditability

class CanonicalCheckbox(CanonicalField):
    field_type: str = "checkbox"
    value: bool

class CanonicalSignature(CanonicalField):
    field_type: str = "signature"
    is_signed: bool

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

class CanonicalSection(BaseModel):
    section_id: str
    title: str
    fields: List[CanonicalField] = Field(default_factory=list)
    tables: List[CanonicalTable] = Field(default_factory=list)

class CanonicalPage(BaseModel):
    page_number: int
    sections: List[CanonicalSection] = Field(default_factory=list)

class CanonicalDocument(BaseModel):
    schema_version: str = "1.0.0"
    document_id: str
    title: str = "Untitled Document"
    pages: List[CanonicalPage] = Field(default_factory=list)
