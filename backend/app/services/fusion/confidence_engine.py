from typing import List
from app.services.fusion.models import ConfidenceBreakdown
from app.services.fusion.evidence_graph import EvidenceGraph, EvidenceEdge

class ConfidenceEngine:
    """
    Heart of the Fusion system. Computes explainable confidence 
    based on aggregated evidence and graph topology.
    """
    def __init__(self, graph: EvidenceGraph):
        self.graph = graph

    def compute_fusion_confidence(self, node_id: str) -> ConfidenceBreakdown:
        """
        Calculates confidence for a node by aggregating inbound support and conflict edges.
        """
        node = self.graph.get_node(node_id)
        if not node:
            raise ValueError("Node not found")
            
        # Initialize a fresh breakdown
        breakdown = ConfidenceBreakdown()
        
        # In a real traversal, we'd aggregate inbound edges to this node.
        # For architecture setup, we demonstrate the pattern:
        inbound_edges = [e for e in self.graph.edges.values() if e.target_id == node_id]
        
        for edge in inbound_edges:
            if edge.edge_type == 'support':
                # e.g., if source was VisualGeometry
                source = self.graph.get_node(edge.source_id)
                # Assign to geometry_score or assignment_score based on source provenance
                # (simplified logic for demonstration)
                breakdown.geometry_score += edge.weight * 0.1
                
            elif edge.edge_type == 'conflict':
                breakdown.conflict_penalty += edge.weight * 0.2
                
            elif edge.edge_type == 'human_correction':
                breakdown.human_override_score = 1.0 # Absolute truth injection

        return breakdown

    def propagate_confidence(self, start_node_id: str):
        """
        Push confidence updates downstream through derived edges.
        """
        # Graph traversal logic to update downstream nodes
        pass

    def apply_confidence_decay(self, node_id: str, depth: int):
        """Apply penalty for highly derived assumptions (long chains of inference)."""
        pass
