"""
TASK-P3-14D — Form.io Export Adapter

Consumes CanonicalDocument and generates an interactive Form.io schema.
Does not access pipeline internals directly.
"""
from typing import Dict, Any
from app.services.schema.models import CanonicalDocument

def export_to_formio(document: CanonicalDocument) -> Dict[str, Any]:
    """
    Translates a CanonicalDocument into a Form.io JSON schema payload.
    """
    components = []
    
    for page in document.pages:
        # We can map Pages to Form.io Panels or just flat lists
        for section in page.sections:
            section_components = []
            
            for field in section.fields:
                comp = {
                    "key": field.field_name,
                    "label": field.field_name,
                    "defaultValue": field.value,
                    "persistent": True,
                    "properties": {
                        "provenance_ref": field.provenance_ref,
                        "confidence_score": field.confidence_score
                    }
                }
                
                if field.field_type == "checkbox":
                    comp["type"] = "checkbox"
                    comp["inputType"] = "checkbox"
                elif field.field_type == "signature":
                    comp["type"] = "signature"
                else:
                    comp["type"] = "textfield"
                    comp["inputType"] = "text"
                    
                section_components.append(comp)
                
            components.append({
                "type": "panel",
                "title": section.title,
                "key": f"panel_{section.section_id[:8]}",
                "components": section_components
            })
            
    return {
        "display": "form",
        "components": components,
        "metadata": {
            "schema_version": document.schema_version,
            "document_id": document.document_id
        }
    }
