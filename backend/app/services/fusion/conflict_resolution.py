from typing import List, Dict, Set, Any
import logging
from app.services.fusion.evidence_graph import EvidenceGraph, EvidenceEdge

logger = logging.getLogger(__name__)

class ConflictResolver:
    """
    TASK-P3-09C — Arbitrates conflicts in the EvidenceGraph deterministically.
    Never deletes nodes. Only adds ConflictEdge(weight) to signal disagreement.
    The Fusion Engine reads edge weights to decide which evidence to trust.
    """
    def __init__(self, graph: EvidenceGraph):
        self.graph = graph

    def resolve_spatial_conflicts(self):
        """
        Find AlignmentEvidence nodes that compete for the same region:
          - Multiple tokens INSIDE the same region   → ambiguous
          - Token crosses boundary between 2 regions → boundary conflict
        For each conflict, add a ConflictEdge between the competing nodes.
        """
        # Group alignment nodes by target region
        region_to_alignments: Dict[str, List[str]] = {}
        for node_id, node in self.graph.nodes.items():
            target = getattr(node, "target_evidence_id", None)
            if target:
                region_to_alignments.setdefault(target, []).append(node_id)

        for region_id, aligned_node_ids in region_to_alignments.items():
            if len(aligned_node_ids) <= 1:
                continue
            # Multiple alignments pointing at same region → register conflict
            for i in range(len(aligned_node_ids)):
                for j in range(i + 1, len(aligned_node_ids)):
                    src, tgt = aligned_node_ids[i], aligned_node_ids[j]
                    if src in self.graph.nodes and tgt in self.graph.nodes:
                        existing = [
                            e for e in self.graph.edges.values()
                            if e.edge_type == "conflicts" and e.source_id == src and e.target_id == tgt
                        ]
                        if not existing:
                            self.graph.add_edge(
                                src, tgt, edge_type="conflicts",
                                weight=0.5,
                                metadata={"reason": "competing_alignments_for_same_region"}
                            )
                            logger.debug(f"CONFLICT: {src[:8]}.. ↔ {tgt[:8]}.. (same region {region_id[:8]})")

    def resolve_text_conflicts(self):
        """
        Semantic conflicts are deferred to Phase 4 (NLP layer).
        Currently a deliberate no-op — this engine is geometry-only.
        """
        pass

    def resolve_anchor_conflicts(self):
        """
        Absolute structural walls (anchors) are not yet wired.
        When Anchors are introduced in Phase 4, any alignment that
        crosses an anchor boundary gets maximum conflict weight here.
        """
        pass

    def arbitrate(self) -> Dict[str, Any]:
        """Run all resolution passes. Returns a summary for observability."""
        pre_edge_count = len(self.graph.edges)
        self.resolve_spatial_conflicts()
        self.resolve_text_conflicts()
        self.resolve_anchor_conflicts()
        new_conflicts = len(self.graph.edges) - pre_edge_count
        logger.debug(f"Conflict arbitration completed. New conflict edges: {new_conflicts}")
        return {"new_conflict_edges": new_conflicts}
