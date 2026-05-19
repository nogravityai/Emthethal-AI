"""
core/canonical_renderers.py — Emthethal AI
===========================================
Two renderers that convert CanonicalFormSchema into target-specific formats.

Rule: Form.io is a CONSUMER of the canonical schema.
      They never own or modify the schema.

Renderers:
  canonical_to_formio(schema)              → Form.io JSON (for QA preview)

"""

import hashlib
import uuid as _uuid
from typing import Any, Dict, List

from .canonical_schema import CanonicalField, CanonicalFormSchema, FieldType

# ── Field type maps ───────────────────────────────────────────────────────────

# CanonicalFieldType → Formio type
_TYPE_MAP: Dict[FieldType, tuple[str, str]] = {
    "pass_fail":    "radio",
    "text":         "textfield",
    "notes":        "textarea",
    "number":       "number",
    "date":         "datetime",
    "select":       "select",
    "multiselect":  "selectboxes",
    "signature":    "signature",
    "kpi_indicator":"htmlelement",
}


# ── Deterministic UUID helper ─────────────────────────────────────────────────

def _det_uuid(namespace: str, key: str) -> str:
    """Produce a deterministic UUID from (namespace, key). Re-push safe."""
    h = hashlib.md5(f"{namespace}:{key}".encode()).hexdigest()
    return str(_uuid.UUID(h))


# ═════════════════════════════════════════════════════════════════════════════
# Renderer 1 — Form.io
# ═════════════════════════════════════════════════════════════════════════════

def canonical_to_formio(schema: CanonicalFormSchema) -> Dict[str, Any]:
    """
    Render a CanonicalFormSchema as a Form.io JSON schema.

    Preserves: sections (as panels), grouped fields, KPI indicators,
    metadata (stored as custom properties), confidence scores.
    Maintains backward-compatibility with the existing QADashboard Form preview.
    """
    components: List[Dict[str, Any]] = []

    for section in schema.sections:
        section_components: List[Dict[str, Any]] = []

        for field in section.fields:
            formio_type = _TYPE_MAP.get(field.field_type, "textfield")
            comp: Dict[str, Any] = {
                "type": formio_type,
                "key": field.key,
                "label": field.label,
                "validate": {"required": field.required},
                "customClass": "fatal-field" if field.is_fatal else "",
                # Store canonical metadata as Form.io custom properties
                "properties": {
                    "canonical_field_type": field.field_type,
                    "is_fatal": str(field.is_fatal).lower(),
                    "schema_hash": schema.short_hash(),
                    "schema_version": schema.schema_version,
                    **{k: str(v) for k, v in field.metadata.items()},
                },
            }

            if field.placeholder:
                comp["placeholder"] = field.placeholder

            if field.field_type == "pass_fail" and field.options:
                comp["values"] = [
                    {"label": o.label, "value": o.value}
                    for o in field.options
                ]

            elif field.field_type in ("select", "multiselect") and field.options:
                if formio_type == "selectboxes":
                    comp["values"] = [
                        {"label": o.label, "value": o.value}
                        for o in field.options
                    ]
                else:
                    comp["data"] = {
                        "values": [
                            {"label": o.label, "value": o.value}
                            for o in field.options
                        ]
                    }

            elif field.field_type == "kpi_indicator":
                label_text = field.label
                comp = {
                    "type": "htmlelement",
                    "tag": "div",
                    "key": field.key,
                    "className": "kpi-indicator",
                    "content": f'<span class="kpi-label">{label_text}</span>',
                }

            section_components.append(comp)

        # Wrap section fields in a Form.io panel
        components.append({
            "type": "panel",
            "key": f"section_{section.id}",
            "title": section.label,
            "collapsible": False,
            "components": section_components,
        })

    # Submit button
    components.append({
        "type": "button",
        "label": "Submit Inspection / إرسال التفتيش",
        "key": "submit_btn",
        "size": "md",
        "block": True,
        "action": "submit",
        "disableOnInvalid": True,
        "theme": "primary",
    })

    return {
        "display": "form",
        "_canonical_version": schema.schema_version,
        "_canonical_hash": schema.schema_hash,
        "components": components,
    }


def canonical_to_criteria(schema: CanonicalFormSchema) -> List[Dict[str, Any]]:
    """
    Render the criteria list (fatal/non-fatal checks) from a canonical schema.
    Used by FastAPI to populate checklist_templates.criteria.
    """
    return [
        {
            "key": f.key,
            "label": f.label,
            "is_fatal": f.is_fatal,
        }
        for s in schema.sections
        for f in s.fields
        if f.field_type not in ("kpi_indicator",)
    ]



