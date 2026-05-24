from typing import List, Dict
from pydantic import BaseModel
from app.models.schemas import TableTopologyEvidence, RegionHierarchyEvidence

class TopologyEvidencePayload(BaseModel):
    table_topologies: List[TableTopologyEvidence]
    region_hierarchy: List[RegionHierarchyEvidence]
    linked_checkboxes: Dict[str, str]
