"""
core/canonical_schema.py — Emthethal AI
=========================================
Canonical Intermediate Schema v2

This is the SINGLE source of truth for every form generated in the system.
Both Form.io JSON forms are RENDERED FROM this schema.

Architecture rule (non-negotiable):
  PDF/DOCX/XLSX
        ↓
  CanonicalFormSchema   ← stored here, versioned, hashed, with full lineage
        ↓
   ┌────────────┬──────────────┐
   ↓            ↓
Form.io
(QA preview)  (field runtime)

Lineage chain preserved in source_trace:
  PDF → Extracted Blocks → Canonical Schema → Form Version
  → Submission → Inspection Result → KPI Analytics

Nothing downstream owns the schema. They only render it.
"""

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

# ── Canonical Field Types ─────────────────────────────────────────────────────
# RULE: Field types must stay semantic and renderer-independent.
# They describe WHAT the data means, never HOW it is displayed.
# Renderers (Form.io, PDF, Flutter, WhatsApp) decide presentation.

FieldType = Literal[
    "pass_fail",    # Radio: Pass / Fail  — maps to radio (Form.io)
    "text",         # Single-line text   — maps to textfield (Form.io)
    "notes",        # Multi-line text    — maps to textarea (Form.io)
    "number",       # Numeric            — maps to number (Form.io)
    "date",         # Date picker        — maps to datetime (Form.io)
    "select",       # Single select      — maps to select (Form.io)
    "multiselect",  # Multi select       — maps to selectboxes (Form.io)
    "signature",    # Digital signature  — maps to signature (Form.io)
    "kpi_indicator",# KPI metric display — maps to htmlelement (Form.io)
]


# ── Field Level ───────────────────────────────────────────────────────────────

class CanonicalFieldOption(BaseModel):
    """Option for select / multiselect / pass_fail fields."""
    value: str
    label: str
    label_ar: Optional[str] = None


class CanonicalField(BaseModel):
    """
    A single form field — semantic definition only.

    STRICT RENDERER-INDEPENDENCE RULE:
    Do NOT add to this class:
      - placeholder text          (UI concern → belongs in renderer hints)
      - CSS classes / layout      - Form.io UI specifics (layout, CSS classes)
      - Form.io-specific props    (renderer concern)
      - display order / sizing    (layout concern → CanonicalSection)

    Only add:
      - what the field MEANS      (label, field_type)
      - what CONSTRAINTS apply    (required, is_fatal, options)
      - what PROVENANCE it has    (metadata: confidence, source_block_id)
    """
    key: str = Field(..., description="Unique key within the form, snake_case")
    label: str
    label_ar: Optional[str] = None           # Bilingual label — semantic content, not UI
    field_type: FieldType
    is_fatal: bool = False                   # Failing this freezes the device
    required: bool = False
    options: Optional[List[CanonicalFieldOption]] = None   # For select/multiselect/pass_fail
    default_value: Optional[Any] = None      # Semantic default — renderer may ignore or use
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "OCR confidence, source_block_id, bounding_box. "
            "Renderer-specific hints may be stored here under a namespaced key "
            "(e.g. 'formio_hint': {...}) "
            "but NEVER at the top level of CanonicalField."
        )
    )

    @model_validator(mode="after")
    def inject_pass_fail_options(self) -> "CanonicalField":
        """Auto-inject Pass/Fail options for pass_fail fields if not provided."""
        if self.field_type == "pass_fail" and not self.options:
            self.options = [
                CanonicalFieldOption(value="pass", label="Pass", label_ar="اجتياز"),
                CanonicalFieldOption(value="fail", label="Fail", label_ar="فشل"),
            ]
        return self


# ── Section Level ─────────────────────────────────────────────────────────────

class CanonicalSection(BaseModel):
    id: str = Field(..., description="Unique section identifier, e.g. 'patient_info'")
    label: str
    label_ar: Optional[str] = None
    display_order: int
    fields: List[CanonicalField]


# ── Form Level (root) ─────────────────────────────────────────────────────────

# ── Document Lineage (Gap #1) ─────────────────────────────────────────────────

class DocumentLineage(BaseModel):
    """
    Full provenance chain: PDF → OCR blocks → this schema.
    Stored once at generation time. Never mutated.
    Enables: debugging, audit, traceability, historical analytics.
    """
    document_id: Optional[int] = Field(
        default=None,
        description="FK to ingested_documents.id"
    )
    source_filename: Optional[str] = None
    pages: List[int] = Field(
        default_factory=list,
        description="Page numbers from source document that contributed to this form."
    )
    block_ids: List[str] = Field(
        default_factory=list,
        description="IDs of OCR/geometry blocks that were used as source material."
    )
    ocr_engine: Optional[str] = Field(
        default=None,
        description="e.g. 'paddleocr', 'pymupdf', 'easyocr'"
    )
    avg_confidence: Optional[float] = Field(
        default=None,
        description="Average OCR/extraction confidence across all source blocks."
    )
    llm_model: Optional[str] = Field(
        default=None,
        description="LLM used for extraction, e.g. 'llama3:8b-instruct-q4_K_M'"
    )
    extraction_metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Any extra pipeline metadata: timing, fallback flags, etc."
    )


# ── Form Schema Root ──────────────────────────────────────────────────────────

class CanonicalFormSchema(BaseModel):
    """
    Root schema. This is what gets stored in checklist_templates.canonical_schema.
    Never modify this after a submission has been recorded against it — create a new version.
    """
    schema_version: str = Field(
        default="2.0.0",
        description="Semver. Bump MAJOR on breaking changes, MINOR on additions."
    )
    schema_hash: str = Field(
        default="",
        description="SHA-256 of the canonical JSON (computed automatically, do not set manually)."
    )
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    source_document_id: Optional[int] = Field(
        default=None,
        description="FK to ingested_documents.id — the source that generated this form."
    )
    title: str
    title_ar: Optional[str] = None
    sections: List[CanonicalSection]
    source_trace: DocumentLineage = Field(
        default_factory=DocumentLineage,
        description=(
            "Full provenance: which PDF pages, which OCR blocks, which engine, "
            "what confidence produced this schema. Immutable after creation."
        )
    )
    form_metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="department, device_name, avg_confidence, form_type, etc."
    )

    @model_validator(mode="after")
    def compute_hash(self) -> "CanonicalFormSchema":
        """
        Compute a deterministic SHA-256 hash of the canonical content.
        The hash excludes: schema_hash itself, generated_at.
        This makes the hash stable across re-generation with the same inputs.
        """
        hashable = {
            "schema_version": self.schema_version,
            "title": self.title,
            "sections": [
                {
                    "id": s.id,
                    "label": s.label,
                    "display_order": s.display_order,
                    "fields": [
                        {
                            "key": f.key,
                            "label": f.label,
                            "field_type": f.field_type,
                            "is_fatal": f.is_fatal,
                            "required": f.required,
                        }
                        for f in s.fields
                    ]
                }
                for s in self.sections
            ]
        }
        raw = json.dumps(hashable, sort_keys=True, ensure_ascii=False)
        self.schema_hash = hashlib.sha256(raw.encode()).hexdigest()
        return self

    @property
    def all_fields(self) -> List[CanonicalField]:
        """Flat list of all fields across all sections."""
        return [f for s in self.sections for f in s.fields]

    @property
    def fatal_fields(self) -> List[CanonicalField]:
        return [f for f in self.all_fields if f.is_fatal]

    def short_hash(self, length: int = 8) -> str:
        return self.schema_hash[:length]
