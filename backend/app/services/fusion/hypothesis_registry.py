from typing import Dict, List, Optional
from app.services.fusion.models import LayoutHypothesis, EvidenceProvenance

class HypothesisRegistry:
    """
    A Typed Evidence Graph managing all hypotheses.
    This replaces flat lists and acts as the central state for the Fusion Engine.
    """
    def __init__(self):
        # hypothesis_id -> LayoutHypothesis
        self._hypotheses: Dict[str, LayoutHypothesis] = {}
        
        # In the future, adjacency and conflict edges can be added here
        # to construct the full Spatial Graph.
        
    def submit(self, hypothesis: LayoutHypothesis) -> str:
        """
        Submit a new piece of evidence (hypothesis) from any subsystem.
        Returns the ID of the registered hypothesis.
        """
        self._hypotheses[hypothesis.hypothesis_id] = hypothesis
        return hypothesis.hypothesis_id
        
    def get(self, hypothesis_id: str) -> Optional[LayoutHypothesis]:
        """Retrieve a specific hypothesis by ID."""
        return self._hypotheses.get(hypothesis_id)
        
    def all(self) -> List[LayoutHypothesis]:
        """Get all hypotheses in the registry."""
        return list(self._hypotheses.values())
        
    def by_type(self, h_type: str) -> List[LayoutHypothesis]:
        """Filter hypotheses by type (e.g., 'table_cell', 'checkbox')."""
        return [h for h in self.all() if h.hypothesis_type == h_type]
        
    def by_page(self, page_number: int) -> List[LayoutHypothesis]:
        """Filter hypotheses by page number."""
        return [h for h in self.all() if h.page_number == page_number]
