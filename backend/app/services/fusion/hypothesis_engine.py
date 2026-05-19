# ============================================================
# CFIS Phase 2 — Layout Hypothesis Engine
# Location: backend/app/services/hypothesis_engine.py
#
# PURPOSE: Centralized layout hypothesis registry.
# NO subsystem may bypass this module (Rule 3).
# ALL subsystems emit LayoutHypotheses into this registry.
# ONLY the Fusion Engine reads from this registry to produce
# canonical LayoutCells.
#
# Supported hypothesis types:
#   table_cell | text_field | checkbox | radio_group |
#   section_header | table_region | text_block | signature_area
#
# Phase 2B additions:
#   make_radio_group_hypothesis()   — clustered checkbox alignment
#   make_merged_cell_hypothesis()   — colspan/rowspan table cells
#   make_signature_hypothesis()     — wide low-fill signature boxes
#   RadioGroupCandidate             — staging model before registry submit
# ============================================================

from __future__ import annotations

import logging
import uuid
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.models.schemas import BoundingBox

logger = logging.getLogger(__name__)

# ── HYPOTHESIS TYPES ──────────────────────────────────────────────────────────

HypothesisType = Literal[
    "table_cell",
    "text_field",
    "checkbox",
    "radio_group",
    "section_header",
    "table_region",
    "text_block",
    "signature_area",
]

# ── HYPOTHESIS PRIMITIVES ─────────────────────────────────────────────────────


class GeometryEvidence(BaseModel):
    """
    The multi-signal confidence matrix for a LayoutHypothesis.
    All three confidence values feed into fusion_confidence via scoring rules.
    """
    geometry_confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    text_confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    structural_confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    fusion_confidence: float = Field(ge=0.0, le=1.0, default=0.0)

    @classmethod
    def from_scores(
        cls,
        geometry: float = 0.0,
        text: float = 0.0,
        structural: float = 0.0,
        *,
        geometry_weight: float = 0.35,
        text_weight: float = 0.45,
        structural_weight: float = 0.20,
    ) -> "GeometryEvidence":
        """Compute fusion_confidence as a weighted sum of the three signals."""
        total_w = geometry_weight + text_weight + structural_weight
        fusion = (
            geometry * geometry_weight
            + text * text_weight
            + structural * structural_weight
        ) / total_w
        return cls(
            geometry_confidence=geometry,
            text_confidence=text,
            structural_confidence=structural,
            fusion_confidence=round(min(1.0, fusion), 4),
        )


class LayoutHypothesis(BaseModel):
    """
    A probabilistic claim about the layout of a region.

    NO subsystem may directly produce final LayoutCells.
    ALL layout subsystems MUST emit LayoutHypothesis objects.
    ONLY the Fusion Engine arbitrates and accepts/rejects hypotheses.

    Rules may:
      - score hypotheses
      - rank competing hypotheses
      - arbitrate between conflicting claims
      - reject hypotheses below threshold

    Rules may NOT:
      - mutate geometry directly
      - override valid native text
      - bypass hypothesis scoring
    """
    hypothesis_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:12])
    hypothesis_type: HypothesisType
    bbox: BoundingBox
    page_number: int = Field(ge=0, default=0)

    # Evidence sources (e.g., "opencv_morphology", "native_text", "pp_structure")
    evidence_sources: List[str] = Field(default_factory=list)

    # Individual scoring signals (0.0 → 1.0)
    geometry_score: float = Field(ge=0.0, le=1.0, default=0.0)
    text_score: float = Field(ge=0.0, le=1.0, default=0.0)
    structural_score: float = Field(ge=0.0, le=1.0, default=0.0)

    # Computed by Fusion Engine
    fusion_score: float = Field(ge=0.0, le=1.0, default=0.0)
    accepted: bool = False

    # Optional enrichment (text content associated with this hypothesis)
    text_content: Optional[str] = None
    widget_type_hint: Optional[str] = None

    def compute_fusion_score(
        self,
        geometry_weight: float = 0.35,
        text_weight: float = 0.45,
        structural_weight: float = 0.20,
    ) -> float:
        """Compute and store the weighted fusion score."""
        total_w = geometry_weight + text_weight + structural_weight
        score = (
            self.geometry_score * geometry_weight
            + self.text_score * text_weight
            + self.structural_score * structural_weight
        ) / total_w
        self.fusion_score = round(min(1.0, score), 4)
        return self.fusion_score

    def overlaps(self, other: "LayoutHypothesis", min_iou: float = 0.25) -> bool:
        """Return True if this hypothesis spatially conflicts with another."""
        try:
            return self.bbox.iou(other.bbox) >= min_iou
        except ValueError:
            return False


# ── HYPOTHESIS REGISTRY ───────────────────────────────────────────────────────


class HypothesisRegistry:
    """
    Centralized registry for all layout hypotheses on a single page.

    Usage:
        registry = HypothesisRegistry(page_number=0)
        registry.submit(hyp)           # from any subsystem
        all_hyps = registry.all()      # read by Fusion Engine only
        accepted = registry.accepted() # after Fusion Engine runs
    """

    def __init__(self, page_number: int = 0) -> None:
        self.page_number = page_number
        self._hypotheses: Dict[str, LayoutHypothesis] = {}
        self._submission_order: List[str] = []

    def submit(self, hyp: LayoutHypothesis) -> str:
        """
        Submit a hypothesis from any subsystem.
        Returns the hypothesis_id for reference.
        Automatically enforces page_number consistency.
        """
        hyp.page_number = self.page_number
        self._hypotheses[hyp.hypothesis_id] = hyp
        self._submission_order.append(hyp.hypothesis_id)
        logger.debug(
            f"Registry[page={self.page_number}]: submitted {hyp.hypothesis_type!r} "
            f"hyp={hyp.hypothesis_id} "
            f"geo={hyp.geometry_score:.2f} txt={hyp.text_score:.2f}"
        )
        return hyp.hypothesis_id

    def submit_many(self, hypotheses: List[LayoutHypothesis]) -> List[str]:
        """Bulk submission."""
        return [self.submit(h) for h in hypotheses]

    def all(self) -> List[LayoutHypothesis]:
        """Return all submitted hypotheses in submission order."""
        return [self._hypotheses[hid] for hid in self._submission_order]

    def by_type(self, hypothesis_type: HypothesisType) -> List[LayoutHypothesis]:
        """Return all hypotheses of a specific type."""
        return [h for h in self.all() if h.hypothesis_type == hypothesis_type]

    def accepted(self) -> List[LayoutHypothesis]:
        """Return all hypotheses accepted by the Fusion Engine."""
        return [h for h in self.all() if h.accepted]

    def rejected(self) -> List[LayoutHypothesis]:
        """Return all hypotheses rejected by the Fusion Engine."""
        return [h for h in self.all() if not h.accepted]

    def accept(self, hypothesis_id: str) -> None:
        """Mark a hypothesis as accepted (called by Fusion Engine only)."""
        if hypothesis_id in self._hypotheses:
            self._hypotheses[hypothesis_id].accepted = True

    def reject(self, hypothesis_id: str) -> None:
        """Mark a hypothesis as rejected (called by Fusion Engine only)."""
        if hypothesis_id in self._hypotheses:
            self._hypotheses[hypothesis_id].accepted = False

    def __len__(self) -> int:
        return len(self._hypotheses)

    def summary(self) -> Dict[str, int]:
        """Return count by hypothesis_type."""
        counts: Dict[str, int] = {}
        for h in self.all():
            counts[h.hypothesis_type] = counts.get(h.hypothesis_type, 0) + 1
        return counts


# ── HYPOTHESIS BUILDERS ───────────────────────────────────────────────────────
# These are factory functions for subsystems to create properly-scored hypotheses
# before submitting to the registry.


def make_checkbox_hypothesis(
    bbox: BoundingBox,
    page_number: int,
    geometry_score: float,
    fill_ratio: float = 0.0,
    shape_score: float = 0.0,
    near_text: Optional[str] = None,
) -> LayoutHypothesis:
    """
    Build a checkbox hypothesis from visual geometry evidence.
    text_score is 0 unless adjacent text is detected (handled by Fusion).
    """
    return LayoutHypothesis(
        hypothesis_type="checkbox",
        bbox=bbox,
        page_number=page_number,
        evidence_sources=["opencv_morphology"],
        geometry_score=geometry_score,
        text_score=0.0,
        structural_score=0.5,  # moderate structural prior
        text_content=near_text,
        widget_type_hint="checkbox",
    )


def make_table_cell_hypothesis(
    bbox: BoundingBox,
    page_number: int,
    geometry_score: float,
    structural_score: float,
    from_grid: bool = True,
) -> LayoutHypothesis:
    """
    Build a table cell hypothesis from structural analysis evidence.
    """
    return LayoutHypothesis(
        hypothesis_type="table_cell",
        bbox=bbox,
        page_number=page_number,
        evidence_sources=["structural_grid" if from_grid else "opencv_contour"],
        geometry_score=geometry_score,
        text_score=0.0,
        structural_score=structural_score,
        widget_type_hint="text",
    )


def make_text_block_hypothesis(
    bbox: BoundingBox,
    page_number: int,
    text_content: str,
    text_confidence: float,
    source: str = "native_text",
) -> LayoutHypothesis:
    """
    Build a text block hypothesis from native text or OCR evidence.
    """
    return LayoutHypothesis(
        hypothesis_type="text_block",
        bbox=bbox,
        page_number=page_number,
        evidence_sources=[source],
        geometry_score=0.3,  # minimal geometric evidence for pure text
        text_score=text_confidence,
        structural_score=0.0,
        text_content=text_content,
        widget_type_hint="text",
    )


def make_section_header_hypothesis(
    bbox: BoundingBox,
    page_number: int,
    text_content: Optional[str] = None,
    structural_score: float = 0.85,
) -> LayoutHypothesis:
    """
    Build a section header hypothesis from structural anchor evidence.
    """
    return LayoutHypothesis(
        hypothesis_type="section_header",
        bbox=bbox,
        page_number=page_number,
        evidence_sources=["opencv_morphology", "structural_anchor"],
        geometry_score=0.8,
        text_score=0.6 if text_content else 0.0,
        structural_score=structural_score,
        text_content=text_content,
        widget_type_hint="text",
    )


# ── PHASE 2B: ADVANCED HYPOTHESIS BUILDERS ───────────────────────────────────


class RadioGroupCandidate(BaseModel):
    """
    Staging container for a set of checkbox hypotheses that are
    spatially aligned and should be submitted as a radio_group.
    Created by fuse_radio_groups() in fusion_engine.py before
    final submission to the registry.
    """
    candidate_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    page_number: int
    checkbox_hypothesis_ids: List[str]  # IDs already in registry
    group_bbox: BoundingBox
    alignment_axis: str  # "horizontal" | "vertical"
    alignment_score: float = Field(ge=0.0, le=1.0)
    label_text: Optional[str] = None  # collected from nearby tokens


def make_radio_group_hypothesis(
    group_bbox: BoundingBox,
    page_number: int,
    checkbox_ids: List[str],
    alignment_score: float,
    alignment_axis: str = "vertical",
    label_text: Optional[str] = None,
) -> LayoutHypothesis:
    """
    Build a radio_group hypothesis from a cluster of aligned checkboxes.

    Phase 2B: alignment pattern detection — checkboxes aligned along an
    axis (same x for vertical, same y for horizontal) → radio group.
    Nearby text tokens become the group label (handled by fusion).
    """
    geo_score = min(0.95, alignment_score * 1.1)  # alignment is strong geo evidence
    return LayoutHypothesis(
        hypothesis_type="radio_group",
        bbox=group_bbox,
        page_number=page_number,
        evidence_sources=["opencv_morphology", "alignment_pattern"],
        geometry_score=geo_score,
        text_score=0.5 if label_text else 0.0,
        structural_score=0.65,
        text_content=label_text,
        widget_type_hint="radio",
    )


def make_merged_cell_hypothesis(
    bbox: BoundingBox,
    page_number: int,
    rowspan: int,
    colspan: int,
    confidence: float = 0.80,
) -> LayoutHypothesis:
    """
    Build a table_cell hypothesis for a merged (spanning) cell.
    Carries span metadata in widget_type_hint for the QA viewer.
    Phase 2B: created by cell_merger.resolve_merged_cells().
    """
    span_label = f"span_{rowspan}r_{colspan}c"
    return LayoutHypothesis(
        hypothesis_type="table_cell",
        bbox=bbox,
        page_number=page_number,
        evidence_sources=["structural_grid", "cell_merger"],
        geometry_score=confidence,
        text_score=0.0,
        structural_score=0.80,
        widget_type_hint=span_label,
    )


def make_signature_hypothesis(
    bbox: BoundingBox,
    page_number: int,
    fill_ratio: float,
    near_text: Optional[str] = None,
) -> LayoutHypothesis:
    """
    Build a signature_area hypothesis from a wide low-fill input box.
    Phase 2B: improves on Phase 2A by scoring fill_ratio explicitly.
    Low fill_ratio = likely empty signature line (not a text field).
    """
    # Emptier boxes → higher confidence this is a signature line
    geo_score = max(0.5, 1.0 - fill_ratio * 2.5)
    return LayoutHypothesis(
        hypothesis_type="signature_area",
        bbox=bbox,
        page_number=page_number,
        evidence_sources=["opencv_morphology", "fill_ratio_analysis"],
        geometry_score=geo_score,
        text_score=0.3 if near_text else 0.0,
        structural_score=0.55,
        text_content=near_text,
        widget_type_hint="signature",
    )
