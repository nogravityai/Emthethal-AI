"""
CFIS v5.2 — ERPNext Custom DocType Adapter

Converts a CanonicalDocument into an ERPNext Custom DocType JSON fixture.
The output can be imported directly in ERPNext via:
  - Fixtures (fixtures/doctype/*.json)
  - Custom DocType Import UI
  - Frappe's import_doc API

Each zone → ERPNext Section Break
Each field → ERPNext field with the correct fieldtype mapping
"""
import re
from typing import Dict, Any

from app.services.schema.models import CanonicalDocument, FieldType


# ── Type Mapping ───────────────────────────────────────────────────────────────
_ERPNEXT_MAP: Dict[str, str] = {
    FieldType.TEXT:       "Data",
    FieldType.NAME:       "Data",
    FieldType.NUMBER:     "Int",
    FieldType.DATE:       "Date",
    FieldType.CHECKBOX:   "Check",
    FieldType.RADIO:      "Select",
    FieldType.DROPDOWN:   "Select",
    FieldType.PHONE:      "Phone",
    FieldType.EMAIL:      "Data",
    FieldType.SIGNATURE:  "Signature",
    FieldType.TABLE:      "Table",
    FieldType.HEADER:     "Section Break",
    FieldType.FORM_TITLE: "Section Break",
    FieldType.UNKNOWN:    "Data",
}


def _snake_case(text: str) -> str:
    """Convert a label to a valid ERPNext fieldname (snake_case, max 140 chars)."""
    # Replace Arabic/special chars with transliterations
    s = re.sub(r'[^\w\s]', '', text, flags=re.UNICODE)
    s = re.sub(r'\s+', '_', s.strip())
    s = s.lower()
    # Ensure starts with letter
    if s and s[0].isdigit():
        s = "f_" + s
    return s[:140] or "field"


def export_to_erpnext(document: CanonicalDocument) -> Dict[str, Any]:
    """
    Export a CanonicalDocument as an ERPNext Custom DocType JSON.

    Returns:
        A dict matching ERPNext DocType fixture format.
    """
    fields = []
    doctype_name = (document.title or document.document_id).strip()

    for page in document.pages:
        for section in page.sections:
            if not section.include_in_form:
                continue

            # Zone → ERPNext Section Break
            fields.append({
                "fieldtype": "Section Break",
                "fieldname": f"sb_{section.section_id[:12]}",
                "label": section.title,
                "collapsible": 0,
            })

            # Column break after section header for better layout
            fields.append({
                "fieldtype": "Column Break",
                "fieldname": f"cb_{section.section_id[:12]}",
            })

            for field in section.fields:
                if not field.include_in_form:
                    continue

                erpnext_type = _ERPNEXT_MAP.get(field.field_type, "Data")
                fieldname = _snake_case(field.field_name)

                fld: Dict[str, Any] = {
                    "fieldtype": erpnext_type,
                    "fieldname": fieldname,
                    "label": field.field_name,
                    "reqd": 0,
                    "in_list_view": 1,
                    "description": (
                        f"Extracted by CFIS | "
                        f"confidence: {field.confidence_score:.0%} | "
                        f"zone: {field.zone_id or 'unzoned'}"
                    ),
                }

                # Type-specific defaults
                if field.field_type == FieldType.CHECKBOX:
                    fld["default"] = "1" if field.value else "0"
                elif field.value is not None:
                    fld["default"] = str(field.value)

                if field.field_type in (FieldType.RADIO, FieldType.DROPDOWN):
                    # Placeholder options — human operator refines via HITL
                    fld["options"] = "خيار 1\nخيار 2\nخيار 3"

                if field.field_type == FieldType.DATE:
                    fld["fieldtype"] = "Date"  # ensure correct

                if field.field_type == FieldType.NUMBER:
                    fld["fieldtype"] = "Float"  # more general than Int

                if field.bbox:
                    fld["description"] += f" | bbox: {field.bbox}"

                fields.append(fld)

    return {
        "name": doctype_name,
        "doctype": "DocType",
        "module": "CFIS Forms",
        "custom": 1,
        "is_submittable": 0,
        "track_changes": 1,
        "fields": fields,
        "permissions": [
            {
                "role": "System Manager",
                "read": 1,
                "write": 1,
                "create": 1,
                "delete": 1,
                "submit": 0,
            }
        ],
        "_cfis_metadata": {
            "schema_version": document.schema_version,
            "document_id": document.document_id,
            "form_title": document.title,
            "generated_by": "CFIS ERPNext Adapter v5.2",
        }
    }
