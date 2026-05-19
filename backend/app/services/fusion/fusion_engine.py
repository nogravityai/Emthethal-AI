"""
TASK-P3-09B — Alignment-Driven FusionEngine

Primary contract:
  AlignmentEvidence → EvidenceGraph → ConsolidatedHypothesis → ResolvedField

The Fusion Engine never touches BoundingBoxes, OCR dicts, or OpenCV primitives.
It reads only the graph that alignment_ingestion.py built.

Migration note: AssignmentEvidence input is kept as a secondary (compat) path
until all callers migrate to AlignmentEvidence. See _ingest_legacy_assignments().
"""
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field
import logging

from app.services.pipeline.pipeline_models import generate_stable_id, PipelineArtifact
from app.services.pipeline.pipeline_context import PipelineContext
from app.services.pipeline.artifact_store import ArtifactStore

from app.services.fusion.evidence_graph import EvidenceGraph
from app.services.fusion.confidence_engine import ConfidenceEngine
from app.services.fusion.conflict_resolution import ConflictResolver
from app.services.fusion.alignment_ingestion import ingest_alignment_evidence, build_alignment_edges
from app.services.fusion.models import (
    ResolvedField, ResolvedFieldProvenance, ConfidenceBreakdown, EvidenceProvenance
)
from app.services.alignment.models import AlignmentEvidence, AlignmentType

logger = logging.getLogger(__name__)


class ConsolidatedHypothesis(BaseModel):
    """
    Intermediate grouping: all AlignmentEvidence that points to the same region.
    Used to aggregate tokens before generating a single ResolvedField.
    """
    consolidation_id: str
    target_region_id: str
    alignment_ids: List[str]           # AlignmentEvidence stable_ids
    ocr_token_ids: List[str]           # source OCRTokenEvidence stable_ids
    max_alignment_score: float
    conflict_count: int = 0


class FusionEngine:
    """
    TASK-P3-09B — Evidence Graph Reduction Engine.
    Input:  AlignmentEvidence list
    Output: ResolvedField list
    """

    def __init__(self):
        # Graph is built fresh per run — no mutable shared state.
        self.graph: Optional[EvidenceGraph] = None

    # ── Public API ─────────────────────────────────────────────────────────────

    def build_graph(self, alignments: List[AlignmentEvidence]) -> EvidenceGraph:
        """Construct the typed EvidenceGraph from alignment evidence."""
        self.graph = EvidenceGraph()
        ingest_alignment_evidence(alignments, self.graph)
        build_alignment_edges(alignments, self.graph)
        return self.graph

    def consolidate_evidence(self, alignments: List[AlignmentEvidence]) -> List[ConsolidatedHypothesis]:
        """
        Group AlignmentEvidence by target region, then run ConflictResolver.
        Returns one ConsolidatedHypothesis per distinct target region.
        """
        if self.graph is None:
            self.build_graph(alignments)

        resolver = ConflictResolver(self.graph)
        conflict_summary = resolver.arbitrate()

        # Group by target region
        region_groups: Dict[str, List[AlignmentEvidence]] = {}
        for ev in alignments:
            region_groups.setdefault(ev.target_evidence_id, []).append(ev)

        consolidations = []
        for region_id, group in region_groups.items():
            # Count conflict edges touching this group
            n_conflicts = sum(
                1 for e in self.graph.edges.values()
                if e.edge_type == "conflicts" and (
                    e.source_id in {ev.stable_id for ev in group} or
                    e.target_id in {ev.stable_id for ev in group}
                )
            )
            c_id = generate_stable_id("consolidation", region_id, *[ev.stable_id for ev in group])
            consolidations.append(ConsolidatedHypothesis(
                consolidation_id=c_id,
                target_region_id=region_id,
                alignment_ids=[ev.stable_id for ev in group],
                ocr_token_ids=[ev.source_evidence_id for ev in group],
                max_alignment_score=max(ev.alignment_score for ev in group),
                conflict_count=n_conflicts
            ))
            logger.debug(f"Consolidated {len(group)} alignments → region {region_id[:12]}.. conflicts={n_conflicts}")

        return consolidations

    def generate_resolved_candidates(
        self,
        consolidations: List[ConsolidatedHypothesis],
        alignments: List[AlignmentEvidence],
        page_number: int = 1,
    ) -> List[ResolvedField]:
        """
        TASK-P3-09B / 09D — Produce ResolvedField with full provenance chain.
        One ResolvedField per ConsolidatedHypothesis (i.e., per spatial region).
        """
        # Build quick lookup: alignment_id → AlignmentEvidence
        align_by_id = {ev.stable_id: ev for ev in alignments}

        resolved = []
        for cons in consolidations:
            # Confidence: penalise conflicts
            conflict_penalty = min(0.4, cons.conflict_count * 0.1)
            breakdown = ConfidenceBreakdown(
                geometry_score=cons.max_alignment_score,
                assignment_score=cons.max_alignment_score,
                conflict_penalty=conflict_penalty
            )

            # Build full provenance trail (TASK-P3-09D)
            prov = ResolvedFieldProvenance(
                ocr_tokens=cons.ocr_token_ids,
                alignment_edges=cons.alignment_ids,
                geometry_regions=[cons.target_region_id],
            )

            # Aggregate text value from tokens (order preserved, no NLP)
            texts = []
            for a_id in cons.alignment_ids:
                ev = align_by_id.get(a_id)
                if ev:
                    # We carry the token id only; text retrieval happens at export
                    pass   # value is populated when OCR evidence is joined at export layer

            field = ResolvedField(
                field_type="inferred",
                value=None,            # populated at Export Layer, not here
                confidence_breakdown=breakdown,
                resolved_provenance=prov,
                supporting_hypotheses=cons.alignment_ids,  # migration compat
                page_number=page_number
            )
            resolved.append(field)

        return resolved


# ── Pipeline Stage ─────────────────────────────────────────────────────────────

class AlignmentFusionStage:
    """
    TASK-P3-09B drop-in pipeline stage.
    Replaces the old FusionStage that depended on AssignmentEvidence.
    """
    stage_name = "alignment_fusion"
    required_artifact_types = ["alignment_evidence"]
    output_artifact_type = "resolved_fields"

    def run(self, context: PipelineContext, store: ArtifactStore) -> PipelineArtifact:
        align_art = store.get(context.artifact_references["alignment_evidence"])
        alignments: List[AlignmentEvidence] = align_art.payload

        engine = FusionEngine()
        consolidations = engine.consolidate_evidence(alignments)
        resolved = engine.generate_resolved_candidates(consolidations, alignments)

        art_id = generate_stable_id("resolved", align_art.artifact_id)
        logger.info(f"Fusion complete: {len(resolved)} ResolvedFields produced from {len(alignments)} alignments.")
        return PipelineArtifact(
            artifact_id=art_id,
            artifact_type="resolved_fields",
            derived_from=[align_art.artifact_id],
            payload=resolved
        )
