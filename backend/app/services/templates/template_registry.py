"""
TASK-P3-13D — Template Registry

Storage and retrieval for Document Templates.
Templates are living structural entities, accumulating a history of human corrections.
"""
from typing import List, Dict, Optional
from pydantic import BaseModel, Field
import threading

from app.services.templates.template_fingerprint import TemplateFingerprint
from app.services.hitl.models import HumanOperation

class DocumentTemplate(BaseModel):
    template_id: str
    name: str
    fingerprint: TemplateFingerprint
    correction_lineage: List[HumanOperation] = Field(default_factory=list)
    version: int = 1


class TemplateRegistry:
    """
    In-memory registry for Document Templates.
    In production, this would be backed by PostgreSQL or a Vector DB for the fingerprints.
    """
    def __init__(self):
        self._templates: Dict[str, DocumentTemplate] = {}
        self._lock = threading.Lock()
        
    def register_template(self, template: DocumentTemplate) -> None:
        with self._lock:
            self._templates[template.template_id] = template
            
    def get_template(self, template_id: str) -> Optional[DocumentTemplate]:
        with self._lock:
            return self._templates.get(template_id)
            
    def get_all_templates(self) -> List[DocumentTemplate]:
        with self._lock:
            return list(self._templates.values())
            
    def add_correction_to_template(self, template_id: str, operation: HumanOperation) -> None:
        """
        Record a human correction so it can be reused when this template is seen again.
        """
        with self._lock:
            template = self._templates.get(template_id)
            if template:
                template.correction_lineage.append(operation)
                template.version += 1


global_template_registry = TemplateRegistry()
