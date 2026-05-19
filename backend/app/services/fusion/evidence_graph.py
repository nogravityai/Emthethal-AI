from typing import Dict, List, Optional, Any
import uuid
from pydantic import BaseModel, Field

from app.services.fusion.models import LayoutHypothesis, HumanCorrectionEvidence

class EvidenceEdge(BaseModel):
    edge_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_id: str
    target_id: str
    edge_type: str  # 'support', 'conflict', 'derived', 'human_correction'
    weight: float = 1.0
    metadata: Dict[str, Any] = Field(default_factory=dict)

class EvidenceGraph:
    """
    A Typed Evidence Graph replacing the flat hypothesis list.
    Manages nodes (Hypotheses, HumanCorrections) and edges (Support, Conflict).
    Essential for traceability, replay, and conflict arbitration.
    """
    def __init__(self):
        self.nodes: Dict[str, Any] = {}
        self.edges: Dict[str, EvidenceEdge] = {}
        self._adjacency_list: Dict[str, List[str]] = {}

    def add_node(self, node: Any) -> str:
        """Add a Hypothesis or Correction as a node."""
        node_id = getattr(node, "hypothesis_id",
                    getattr(node, "correction_id",
                    getattr(node, "evidence_id",
                    getattr(node, "stable_id", None))))
        if not node_id:
            raise ValueError("Node must have hypothesis_id, correction_id, evidence_id, or stable_id")
            
        self.nodes[node_id] = node
        if node_id not in self._adjacency_list:
            self._adjacency_list[node_id] = []
        return node_id

    def add_edge(self, source_id: str, target_id: str, edge_type: str, weight: float = 1.0, metadata: Dict = None):
        """Add a typed edge between two evidence nodes."""
        if source_id not in self.nodes or target_id not in self.nodes:
            raise ValueError("Both source and target must exist in the graph.")
            
        edge = EvidenceEdge(
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            weight=weight,
            metadata=metadata or {}
        )
        self.edges[edge.edge_id] = edge
        self._adjacency_list[source_id].append(edge.edge_id)
        
    def get_node(self, node_id: str) -> Optional[Any]:
        return self.nodes.get(node_id)
        
    def get_edges(self, node_id: str, edge_type: str = None) -> List[EvidenceEdge]:
        """Get all outbound edges for a node, optionally filtered by type."""
        edges = [self.edges[eid] for eid in self._adjacency_list.get(node_id, [])]
        if edge_type:
            edges = [e for e in edges if e.edge_type == edge_type]
        return edges
