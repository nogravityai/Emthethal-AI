"""
TASK-P3-14B — Schema Builder

Converts ResolvedFields into a CanonicalDocument.
Normalizes layout into a business-safe logical hierarchy.
"""
from typing import List, Dict, Any
import uuid

from app.services.fusion.models import ResolvedField
from app.services.schema.models import (
    CanonicalDocument, CanonicalPage, CanonicalSection, 
    CanonicalField, CanonicalCheckbox
)

def build_canonical_document(document_id: str, resolved_fields: List[ResolvedField]) -> CanonicalDocument:
    """
    Groups ResolvedFields into a normalized CanonicalDocument structure.
    Currently places all fields in a single section on page 1 as a baseline.
    Future layout logic will separate sections/tables deterministically.
    """
    canonical_fields = []
    
    # Sort fields by Y coordinate (simple reading order heuristic)
    # We don't have direct access to bbox here without looking at the provenance edges,
    # but for schema construction, we assume fields are provided in order, or we can sort later.
    
    for rf in resolved_fields:
        # Determine field type based on the resolved string value or hints
        val_str = str(rf.value).strip().lower()
        if val_str in ["[x]", "[v]", "checked", "true"]:
            c_field = CanonicalCheckbox(
                field_id=rf.field_id,
                field_name=f"Field_{rf.field_id[:8]}",
                value=True,
                confidence_score=rf.confidence_breakdown.final_score,
                provenance_ref=rf.field_id
            )
        elif val_str in ["[ ]", "unchecked", "false"]:
            c_field = CanonicalCheckbox(
                field_id=rf.field_id,
                field_name=f"Field_{rf.field_id[:8]}",
                value=False,
                confidence_score=rf.confidence_breakdown.final_score,
                provenance_ref=rf.field_id
            )
        else:
            c_field = CanonicalField(
                field_id=rf.field_id,
                field_name=f"Field_{rf.field_id[:8]}",
                value=rf.value,
                confidence_score=rf.confidence_breakdown.final_score,
                provenance_ref=rf.field_id
            )
        canonical_fields.append(c_field)
        
    main_section = CanonicalSection(
        section_id=str(uuid.uuid4()),
        title="Main Content",
        fields=canonical_fields
    )
    
    page = CanonicalPage(
        page_number=1,
        sections=[main_section]
    )
    
    return CanonicalDocument(
        document_id=document_id,
        pages=[page]
    )
