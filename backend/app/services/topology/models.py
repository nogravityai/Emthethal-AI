from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from app.models.schemas import TableTopologyEvidence, RegionHierarchyEvidence
from app.core.forms.models import FormGraph

class TopologyEvidencePayload(BaseModel):
    table_topologies: List[TableTopologyEvidence]
    region_hierarchy: List[RegionHierarchyEvidence]
    linked_checkboxes: Dict[str, str]
    zones: List[Dict[str, Any]] = []
    form_graph: Optional[FormGraph] = None


