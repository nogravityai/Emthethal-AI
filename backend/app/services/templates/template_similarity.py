"""
TASK-P3-13E — Similarity Retrieval

Finds the most structurally similar template to a given document fingerprint.
"""
from typing import Optional, List
from pydantic import BaseModel

from app.services.templates.template_fingerprint import TemplateFingerprint
from app.services.templates.drift_detection import calculate_drift_score, classify_drift
from app.services.templates.template_registry import DocumentTemplate, global_template_registry

class TemplateMatchResult(BaseModel):
    template: DocumentTemplate
    drift_score: float
    drift_classification: str
    is_match: bool


def find_best_template_match(fingerprint: TemplateFingerprint, max_drift_threshold: float = 0.3) -> Optional[TemplateMatchResult]:
    """
    Retrieves the template with the lowest structural drift score.
    Returns None if no template is within the acceptable drift threshold.
    """
    templates = global_template_registry.get_all_templates()
    if not templates:
        return None
        
    best_match = None
    lowest_drift = float('inf')
    
    for template in templates:
        drift = calculate_drift_score(template.fingerprint, fingerprint)
        if drift < lowest_drift:
            lowest_drift = drift
            best_match = template
            
    if best_match and lowest_drift <= max_drift_threshold:
        return TemplateMatchResult(
            template=best_match,
            drift_score=lowest_drift,
            drift_classification=classify_drift(lowest_drift),
            is_match=True
        )
        
    return None
