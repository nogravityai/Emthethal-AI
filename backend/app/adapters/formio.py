# ============================================================
# CFIS Form.io Adapter
# Location: backend/app/adapters/formio.py
# DocumentOutput → Form.io JSON schema
# Arabic labels primary. RTL layout.
# Grouped by page → row → column (sorted deterministically).
# ============================================================

from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.models.schemas import DocumentOutput, FormField

WIDGET_MAP: Dict[str, Dict[str, Any]] = {
    "text":               {"type": "textfield"},
    "number":             {"type": "number"},
    "radio":              {"type": "radio"},
    "select":             {"type": "select"},
    "date":               {"type": "datetime", "format": "yyyy-MM-dd"},
    "datetime":           {"type": "datetime", "format": "yyyy-MM-dd HH:mm"},
    "textarea":           {"type": "textarea"},
    "checkbox":           {"type": "checkbox"},
    "repeating_rows":     {"type": "datagrid"},
    "signature":          {"type": "signature"},
    "nested_group":       {"type": "panel"},
    "hierarchical_table": {"type": "htmlelement"},
    "file":               {"type": "file"},
    "unknown":            {"type": "textfield"},
}


def _field_to_formio(field: FormField) -> Dict[str, Any]:
    base = WIDGET_MAP.get(field.runtime_widget, {"type": "textfield"}).copy()
    label   = field.semantic_label_ar or field.semantic_label or ""
    tooltip = field.semantic_label_en or ""

    component: Dict[str, Any] = {
        **base,
        "key": f"f_{field.field_id.replace('-', '')[:32]}",
        "label": label,
        "tooltip": tooltip,
        "validate": {"required": field.validation == "required"},
        "rtl": field.is_rtl,
        "disabled": False,
        "hidden": False,
        "properties": {
            "field_id":        field.field_id,
            "cell_id":         field.cell_id,
            "row_index":       field.row_index,
            "col_index":       field.column_index,
            "page_number":     field.page_number,
            "confidence":      round(field.confidence, 3),
            "language":        field.language,
            "kpi_code":        field.kpi_code or "",
            "human_corrected": field.human_corrected,
            "needs_qa":        field.needs_qa,
            "source":          field.source,
        },
    }

    if field.runtime_widget in ("radio", "select"):
        options = field.options_ar or field.options or []
        if options:
            component["values"] = [
                {"label": opt, "value": f"opt_{i}"}
                for i, opt in enumerate(options)
            ]
        else:
            # Degrade to textfield if no options detected
            component = {
                "type": "textfield",
                "key": component["key"],
                "label": label,
                "tooltip": f"{tooltip} [options not detected — review]".strip(),
                "validate": component["validate"],
                "rtl": field.is_rtl,
                "properties": component["properties"],
            }

    return component


def convert_to_formio(doc: DocumentOutput) -> Dict[str, Any]:
    """
    Convert approved DocumentOutput to Form.io JSON schema.
    Groups: page → row → column (sorted deterministically).
    Multi-field rows → columns layout (12-column grid).
    Arabic RTL when primary_language is 'ar' or 'ar_en'.
    """
    is_rtl = doc.primary_language in ("ar", "ar_en")
    dir_attr = "rtl" if is_rtl else "ltr"

    # Group fields: page → row → list of fields
    by_page_row: Dict[int, Dict[int, List[FormField]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for field in doc.fields:
        by_page_row[field.page_number][field.row_index].append(field)

    components: List[Dict[str, Any]] = []

    # Document header HTML element
    components.append({
        "type": "htmlelement",
        "tag": "div",
        "content": (
            f'<div dir="{dir_attr}" style="'
            f'padding:12px 16px;border-bottom:2px solid #e5e7eb;'
            f'margin-bottom:16px;background:#f9fafb;">'
            f'<strong>{doc.source_file}</strong>'
            f'<span style="float:{"left" if is_rtl else "right"};'
            f'color:#6b7280;font-size:12px;">'
            f'ID: {doc.document_id[:8]}\u2026 | '
            f'Fields: {len(doc.fields)} | '
            f'Language: {doc.primary_language} | '
            f'Mode: {doc.fingerprint.extraction_mode}'
            f'</span></div>'
        ),
        "key": "cfis_doc_header",
        "label": "",
    })

    total_pages = len(by_page_row)

    for page_num in sorted(by_page_row.keys()):
        if total_pages > 1:
            components.append({
                "type": "htmlelement",
                "tag": "div",
                "content": (
                    f'<div style="color:#9ca3af;font-size:11px;'
                    f'margin:8px 0;padding:4px 0;border-top:1px solid #f3f4f6;">'
                    f'\u0635\u0641\u062d\u0629 {page_num + 1} / {total_pages}</div>'
                ),
                "key": f"cfis_page_sep_{page_num}",
                "label": "",
            })

        for row_idx in sorted(by_page_row[page_num].keys()):
            row_fields = sorted(
                by_page_row[page_num][row_idx],
                # For RTL: rightmost column (highest index in visual = index 0) first
                key=lambda f: -f.column_index if is_rtl else f.column_index,
            )

            if len(row_fields) == 1:
                # Single field → plain component
                components.append(_field_to_formio(row_fields[0]))
            else:
                # Multiple fields in a row → columns layout
                total_width = 12  # Form.io 12-column grid
                col_width = max(1, total_width // len(row_fields))
                remainder = total_width - col_width * len(row_fields)

                columns = []
                for i, field in enumerate(row_fields):
                    w = col_width + (1 if i == 0 and remainder > 0 else 0)
                    columns.append({
                        "components": [_field_to_formio(field)],
                        "width": w,
                        "offset": 0,
                        "push": 0,
                        "pull": 0,
                        "size": "md",
                    })

                components.append({
                    "type": "columns",
                    "key": f"cfis_row_p{page_num}_r{row_idx}",
                    "label": "",
                    "columns": columns,
                    "autoAdjust": True,
                })

    return {
        "type": "form",
        "display": "form",
        "settings": {
            "rtl": is_rtl,
            "pdf": {},
        },
        "components": components,
        "metadata": {
            "document_id":      doc.document_id,
            "source_file":      doc.source_file,
            "primary_language": doc.primary_language,
            "extraction_mode":  doc.fingerprint.extraction_mode,
            "layout_hash":      doc.fingerprint.layout_hash,
            "qa_approved":      doc.qa_status == "approved",
            "approved_by":      doc.approved_by,
            "approved_at":      doc.approved_at.isoformat() if doc.approved_at else None,
            "generated_at":     datetime.now(timezone.utc).isoformat(),
            "cfis_version":     "3.0",
            "schema_version":   "2",
        },
    }
