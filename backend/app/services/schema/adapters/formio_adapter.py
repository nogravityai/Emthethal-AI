"""
CFIS v5.2 — Form.io Export Adapter  [Zone-Aware + Full Field Type Mapping]

Consumes CanonicalDocument and generates an interactive Form.io schema.
Does not access pipeline internals directly.

Field type → Form.io component mapping:
  text / name  → textfield
  number       → number
  date         → datetime
  checkbox     → checkbox
  radio        → radio
  dropdown     → select
  phone        → phoneNumber
  email        → email
  signature    → signature
  table        → datagrid
  header       → htmlelement (section label)
  (skipped)    → form_title, unknown
"""
import re
from typing import Dict, Any

from app.services.schema.models import CanonicalDocument, FieldType


# ── Type Mapping ───────────────────────────────────────────────────────────────
_FORMIO_MAP: Dict[str, str] = {
    FieldType.TEXT:       "textfield",
    FieldType.NAME:       "textfield",
    FieldType.NUMBER:     "number",
    FieldType.DATE:       "datetime",
    FieldType.CHECKBOX:   "checkbox",
    FieldType.RADIO:      "radio",
    FieldType.DROPDOWN:   "select",
    FieldType.PHONE:      "phoneNumber",
    FieldType.EMAIL:      "email",
    FieldType.SIGNATURE:  "signature",
    FieldType.TABLE:      "datagrid",
    FieldType.HEADER:     "htmlelement",
    FieldType.UNKNOWN:    "textfield",
}


def _safe_key(label: str) -> str:
    """Generate a Form.io-safe component key from a label."""
    s = re.sub(r'[^\w\s]', '', label or '', flags=re.UNICODE)
    s = re.sub(r'\s+', '_', s.strip()).lower()
    return (s[:64] or "field") + "_" + label[:4].encode('utf-8').hex()[:6]


def export_to_formio(document: CanonicalDocument) -> Dict[str, Any]:
    """
    Translate a CanonicalDocument into a Form.io JSON schema.

    Each CanonicalSection → Form.io Panel component.
    Each CanonicalField → typed Form.io component inside the panel.
    Sections/Fields with include_in_form=False are excluded.
    """
    components = []

    for page in document.pages:
        for section in page.sections:
            if not section.include_in_form:
                continue

            section_components = []

            for field in section.fields:
                if not field.include_in_form:
                    continue

                comp_type = _FORMIO_MAP.get(field.field_type, "textfield")
                key = _safe_key(field.field_name)

                comp: Dict[str, Any] = {
                    "type": comp_type,
                    "key": key,
                    "label": field.field_name,
                    "defaultValue": field.value,
                    "persistent": True,
                    "properties": {
                        "provenance_ref": field.provenance_ref,
                        "confidence_score": round(field.confidence_score, 4),
                        "zone_id": field.zone_id,
                        "cfis_field_type": field.field_type,
                    }
                }

                # Type-specific enhancements
                if field.field_type == FieldType.DATE:
                    comp["format"] = "yyyy-MM-dd"
                    comp["enableTime"] = False
                    comp["defaultValue"] = str(field.value) if field.value else ""

                elif field.field_type == FieldType.CHECKBOX:
                    comp["defaultValue"] = bool(field.value)

                elif field.field_type in (FieldType.RADIO, FieldType.DROPDOWN):
                    comp["data"] = {
                        "values": [
                            {"label": "خيار 1", "value": "option_1"},
                            {"label": "خيار 2", "value": "option_2"},
                            {"label": "خيار 3", "value": "option_3"},
                        ]
                    }

                elif field.field_type == FieldType.SIGNATURE:
                    comp["footer"] = "التوقيع"

                elif field.field_type == FieldType.HEADER:
                    comp["content"] = f"<h4>{field.field_name}</h4>"
                    comp["refreshOnChange"] = False

                elif field.field_type == FieldType.NUMBER:
                    comp["validate"] = {"required": False}

                section_components.append(comp)

            # Wrap in a collapsible panel per zone/section
            panel = {
                "type": "panel",
                "title": section.title,
                "key": f"panel_{section.section_id[:12]}",
                "collapsible": True,
                "collapsed": False,
                "theme": "default",
                "components": section_components,
                "properties": {
                    "zone_type": section.zone_type,
                    "include_in_form": section.include_in_form,
                }
            }
            components.append(panel)

    return {
        "display": "form",
        "components": components,
        "title": document.title,
        "metadata": {
            "schema_version": document.schema_version,
            "document_id": document.document_id,
            "form_title": document.title,
            "generated_by": "CFIS Form.io Adapter v5.2",
        }
    }
