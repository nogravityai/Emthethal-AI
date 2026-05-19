"""
TASK-P3-09A — Alignment Evidence Ingestion into EvidenceGraph

Converts AlignmentEvidence list into Graph Nodes + Weighted Edges.
The Fusion Engine consumes this graph — never raw bboxes or OCR dicts.
"""
from typing import List, Dict, Set
import logging

from app.services.alignment.models import AlignmentEvidence, AlignmentType
from app.services.fusion.evidence_graph import EvidenceGraph

logger = logging.getLogger(__name__)

# Edge weights by alignment type — determines how strongly an alignment
# supports the token→region binding hypothesis.
ALIGNMENT_WEIGHTS: Dict[AlignmentType, float] = {
    AlignmentType.TOKEN_INSIDE_REGION:    1.0,
    AlignmentType.TOKEN_TOUCHING_REGION:  0.6,
    AlignmentType.TOKEN_CROSSES_BOUNDARY: 0.2,   # weak — needs conflict edge too
}


def ingest_alignment_evidence(
    alignments: List[AlignmentEvidence],
    graph: EvidenceGraph,
) -> EvidenceGraph:
    """
    Step 1 — Add every AlignmentEvidence as a node in the graph.
    The node carries the full provenance chain (source token, target region, score).
    """
    for ev in alignments:
        graph.add_node(ev)   # stable_id is used as node key (see evidence_graph.py)
    logger.debug(f"Ingested {len(alignments)} AlignmentEvidence nodes into graph.")
    return graph


def build_alignment_edges(
    alignments: List[AlignmentEvidence],
    graph: EvidenceGraph,
) -> EvidenceGraph:
    """
    Step 2 — Wire typed edges between AlignmentEvidence nodes and
    their source (OCR token) / target (Spatial Region) nodes.

    Edge types:
      'supports'  — alignment strongly backs the token-region binding
      'conflicts' — token crosses boundary (ambiguous binding)

    IMPORTANT: Crossing-boundary tokens emit BOTH a weak support edge
    AND a conflict edge so ConflictResolver can arbitrate later.
    The engine never silently drops ambiguous evidence.
    """
    # Track which regions already have an INSIDE token attached.
    # If a second INSIDE token appears for the same region, they compete.
    region_inside_tokens: Dict[str, List[str]] = {}

    for ev in alignments:
        if ev.alignment_type == AlignmentType.TOKEN_INSIDE_REGION:
            region_inside_tokens.setdefault(ev.target_evidence_id, []).append(ev.stable_id)

    for ev in alignments:
        weight = ALIGNMENT_WEIGHTS[ev.alignment_type]

        # Emit support edge: AlignmentEvidence → target region
        if ev.target_evidence_id in graph.nodes:
            graph.add_edge(
                ev.stable_id,
                ev.target_evidence_id,
                edge_type="supports",
                weight=weight,
                metadata={"alignment_type": ev.alignment_type.value, "score": ev.alignment_score}
            )

        # Extra conflict edge for boundary crossings
        if ev.alignment_type == AlignmentType.TOKEN_CROSSES_BOUNDARY:
            if ev.target_evidence_id in graph.nodes:
                graph.add_edge(
                    ev.stable_id,
                    ev.target_evidence_id,
                    edge_type="conflicts",
                    weight=1.0 - weight,
                    metadata={"reason": "token_crosses_boundary"}
                )

        # Competition conflict: two INSIDE tokens for the same region
        competing = region_inside_tokens.get(ev.target_evidence_id, [])
        if ev.alignment_type == AlignmentType.TOKEN_INSIDE_REGION and len(competing) > 1:
            for other_id in competing:
                if other_id != ev.stable_id and other_id in graph.nodes:
                    graph.add_edge(
                        ev.stable_id,
                        other_id,
                        edge_type="conflicts",
                        weight=0.5,
                        metadata={"reason": "multiple_tokens_inside_same_region"}
                    )

    logger.debug("Alignment edges built.")
    return graph
