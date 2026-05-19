# ============================================================
# CFIS Phase 2B — Border Inference Engine
# Location: backend/app/services/border_inference.py
#
# PURPOSE: Handle partially-detected table borders. Real-world
# forms often have:
#   - Faint ink lines that morphology missed (gaps in a row border)
#   - Missing column separators inferred from row alignment
#   - Scanned noise that broke a continuous line into fragments
#
# ALGORITHM:
#   1. Segment-grouping: cluster line fragments by axis + position
#   2. Gap detection: find spans between fragment endpoints
#   3. Gap scoring: score each gap by alignment evidence
#   4. Gap-filling: emit inferred line segments for high-score gaps
#   5. Border confidence: recalculate per-edge confidence after fill
#
# RULE 3: All outputs are InferredBorderFragment objects, NOT
# LayoutCells. They feed back into structural_analysis.build_table_grids().
#
# RULE 6: Every inferred geometry emits an AuditRecord so the
# debug viewer can distinguish detected vs inferred edges.
# ============================================================

from __future__ import annotations

import logging
import uuid
from typing import Dict, List, Optional, Tuple

import numpy as np
from pydantic import BaseModel, Field

from app.models.schemas import BoundingBox, CoordinateSpace
from app.services.geometry.visual_geometry import DetectedLine

logger = logging.getLogger(__name__)

# ── CONFIGURATION ─────────────────────────────────────────────────────────────

# Maximum gap (in PAGE_PIXELS) to attempt filling
MAX_FILLABLE_GAP_PX = 80.0

# Minimum alignment score to emit an inferred fragment
MIN_ALIGNMENT_SCORE = 0.55

# Tolerance for snapping co-linear fragments to the same axis position
AXIS_SNAP_TOLERANCE = 6.0

# Minimum length (px) for a fragment to be considered a genuine line piece
MIN_FRAGMENT_LENGTH_PX = 20.0


# ── DATA MODELS ───────────────────────────────────────────────────────────────


class BorderFragment(BaseModel):
    """
    A detected line fragment (subset of a full table border).
    Multiple fragments on the same axis + position = one incomplete border.
    """
    fragment_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    orientation: str          # "horizontal" | "vertical"
    axis_position: float      # y-coordinate for H lines, x-coordinate for V lines
    start: float              # x1 for H, y1 for V
    end: float                # x2 for H, y2 for V
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    is_inferred: bool = False


class InferredBorderFragment(BaseModel):
    """
    A gap-filled border segment inferred by alignment evidence.
    Carries an audit trail for the geometry debugger (Rule 6).
    """
    fragment_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    orientation: str
    axis_position: float
    start: float
    end: float
    alignment_score: float = Field(ge=0.0, le=1.0)
    gap_px: float             # original gap size before fill
    fill_reason: str          # "aligned_fragments" | "column_projection" | "row_projection"
    audit_note: str = ""


class GapFillAuditRecord(BaseModel):
    """
    Audit record for the geometry debugger. Documents every gap-fill decision.
    Required by Rule 6 (transformation audit trail).
    """
    audit_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    orientation: str
    axis_position: float
    gap_start: float
    gap_end: float
    gap_px: float
    alignment_score: float
    accepted: bool
    reject_reason: Optional[str] = None


class BorderInferenceResult(BaseModel):
    """
    Output of run_border_inference() for one page.
    Combines original fragments with inferred additions.
    """
    original_fragments: List[BorderFragment] = Field(default_factory=list)
    inferred_fragments: List[InferredBorderFragment] = Field(default_factory=list)
    audit_records: List[GapFillAuditRecord] = Field(default_factory=list)
    total_gaps_found: int = 0
    total_gaps_filled: int = 0

    def all_as_detected_lines(
        self,
        page_width: int,
        page_height: int,
    ) -> List[DetectedLine]:
        """
        Convert both original and inferred fragments back to DetectedLine
        objects so they can be consumed by build_table_grids() directly.
        Inferred lines carry confidence=0.65 (lower than detected=1.0).
        """
        from app.services.coordinate_trace import CoordinateTransformTrace
        trace = CoordinateTransformTrace.identity("page_pixels")
        lines: List[DetectedLine] = []

        for frag in self.original_fragments:
            if frag.orientation == "horizontal":
                lines.append(DetectedLine(
                    x1=frag.start, y1=frag.axis_position,
                    x2=frag.end, y2=frag.axis_position,
                    orientation="horizontal",
                    thickness=1.5,
                    confidence=frag.confidence,
                    trace=trace,
                ))
            else:
                lines.append(DetectedLine(
                    x1=frag.axis_position, y1=frag.start,
                    x2=frag.axis_position, y2=frag.end,
                    orientation="vertical",
                    thickness=1.5,
                    confidence=frag.confidence,
                    trace=trace,
                ))

        for inf in self.inferred_fragments:
            conf = min(0.75, inf.alignment_score)
            if inf.orientation == "horizontal":
                lines.append(DetectedLine(
                    x1=inf.start, y1=inf.axis_position,
                    x2=inf.end, y2=inf.axis_position,
                    orientation="horizontal",
                    thickness=1.0,
                    confidence=conf,
                    trace=trace,
                ))
            else:
                lines.append(DetectedLine(
                    x1=inf.axis_position, y1=inf.start,
                    x2=inf.axis_position, y2=inf.end,
                    orientation="vertical",
                    thickness=1.0,
                    confidence=conf,
                    trace=trace,
                ))

        return lines


# ── PUBLIC API ────────────────────────────────────────────────────────────────


def run_border_inference(
    lines: List[DetectedLine],
    page_width: int,
    page_height: int,
    max_gap_px: float = MAX_FILLABLE_GAP_PX,
    min_alignment_score: float = MIN_ALIGNMENT_SCORE,
) -> BorderInferenceResult:
    """
    Main entry point for Phase 2B border inference.

    Process:
      1. Convert DetectedLines → BorderFragments (group by orientation+axis)
      2. For each axis group, find gaps between sorted fragments
      3. Score each gap by alignment with perpendicular lines
      4. Fill high-confidence gaps with InferredBorderFragments
      5. Return a BorderInferenceResult with full audit trail

    The result can be converted back to DetectedLines via
    result.all_as_detected_lines() for direct use by build_table_grids().
    """
    result = BorderInferenceResult()

    # Step 1: Convert lines → fragments, grouped by (orientation, axis_position)
    h_groups = _group_fragments(
        [l for l in lines if l.orientation == "horizontal"],
        orientation="horizontal",
    )
    v_groups = _group_fragments(
        [l for l in lines if l.orientation == "vertical"],
        orientation="vertical",
    )

    all_fragments: List[BorderFragment] = []
    for fragments in h_groups.values():
        all_fragments.extend(fragments)
    for fragments in v_groups.values():
        all_fragments.extend(fragments)

    result.original_fragments = all_fragments

    # Collect all axis positions for cross-axis alignment scoring
    h_axis_positions = sorted(h_groups.keys())
    v_axis_positions = sorted(v_groups.keys())

    # Step 2-4: Find and fill gaps in horizontal groups
    for axis_pos, fragments in h_groups.items():
        gaps = _find_gaps(fragments, "horizontal")
        result.total_gaps_found += len(gaps)

        for gap_start, gap_end, gap_px in gaps:
            if gap_px > max_gap_px:
                _emit_audit(result, "horizontal", axis_pos, gap_start,
                            gap_end, gap_px, 0.0, False,
                            f"gap too large ({gap_px:.0f}px > {max_gap_px:.0f}px)")
                continue

            score = _score_horizontal_gap(
                axis_pos, gap_start, gap_end,
                v_axis_positions, h_axis_positions,
            )

            if score >= min_alignment_score:
                result.inferred_fragments.append(InferredBorderFragment(
                    orientation="horizontal",
                    axis_position=axis_pos,
                    start=gap_start,
                    end=gap_end,
                    alignment_score=score,
                    gap_px=gap_px,
                    fill_reason="aligned_fragments",
                    audit_note=f"v_axes={len(v_axis_positions)}, score={score:.3f}",
                ))
                result.total_gaps_filled += 1
                _emit_audit(result, "horizontal", axis_pos, gap_start,
                            gap_end, gap_px, score, True)
            else:
                _emit_audit(result, "horizontal", axis_pos, gap_start,
                            gap_end, gap_px, score, False,
                            f"alignment_score {score:.3f} < {min_alignment_score}")

    # Step 2-4: Find and fill gaps in vertical groups
    for axis_pos, fragments in v_groups.items():
        gaps = _find_gaps(fragments, "vertical")
        result.total_gaps_found += len(gaps)

        for gap_start, gap_end, gap_px in gaps:
            if gap_px > max_gap_px:
                _emit_audit(result, "vertical", axis_pos, gap_start,
                            gap_end, gap_px, 0.0, False,
                            f"gap too large ({gap_px:.0f}px > {max_gap_px:.0f}px)")
                continue

            score = _score_vertical_gap(
                axis_pos, gap_start, gap_end,
                h_axis_positions, v_axis_positions,
            )

            if score >= min_alignment_score:
                result.inferred_fragments.append(InferredBorderFragment(
                    orientation="vertical",
                    axis_position=axis_pos,
                    start=gap_start,
                    end=gap_end,
                    alignment_score=score,
                    gap_px=gap_px,
                    fill_reason="aligned_fragments",
                    audit_note=f"h_axes={len(h_axis_positions)}, score={score:.3f}",
                ))
                result.total_gaps_filled += 1
                _emit_audit(result, "vertical", axis_pos, gap_start,
                            gap_end, gap_px, score, True)
            else:
                _emit_audit(result, "vertical", axis_pos, gap_start,
                            gap_end, gap_px, score, False,
                            f"alignment_score {score:.3f} < {min_alignment_score}")

    logger.info(
        f"border_inference: {len(result.original_fragments)} fragments, "
        f"{result.total_gaps_found} gaps found, "
        f"{result.total_gaps_filled} gaps filled, "
        f"{len(result.audit_records)} audit records"
    )
    return result


# ── INTERNAL HELPERS ──────────────────────────────────────────────────────────


def _group_fragments(
    lines: List[DetectedLine],
    orientation: str,
) -> Dict[float, List[BorderFragment]]:
    """
    Group line fragments by their axis position (y for H, x for V).
    Uses AXIS_SNAP_TOLERANCE to merge near-identical positions.
    """
    if not lines:
        return {}

    # Collect raw (axis_pos, start, end, confidence)
    raw: List[Tuple[float, float, float, float]] = []
    for line in lines:
        if orientation == "horizontal":
            axis = line.y1
            start = min(line.x1, line.x2)
            end = max(line.x1, line.x2)
        else:
            axis = line.x1
            start = min(line.y1, line.y2)
            end = max(line.y1, line.y2)
        length = end - start
        if length >= MIN_FRAGMENT_LENGTH_PX:
            raw.append((axis, start, end, line.confidence))

    if not raw:
        return {}

    # Sort by axis position, then snap nearby positions together
    raw.sort(key=lambda r: r[0])
    groups: Dict[float, List[BorderFragment]] = {}
    current_axis = raw[0][0]
    current_group: List[BorderFragment] = []

    for axis, start, end, conf in raw:
        if abs(axis - current_axis) <= AXIS_SNAP_TOLERANCE:
            current_group.append(BorderFragment(
                orientation=orientation,
                axis_position=current_axis,
                start=start,
                end=end,
                confidence=conf,
            ))
        else:
            if current_group:
                groups[current_axis] = current_group
            current_axis = axis
            current_group = [BorderFragment(
                orientation=orientation,
                axis_position=axis,
                start=start,
                end=end,
                confidence=conf,
            )]

    if current_group:
        groups[current_axis] = current_group

    return groups


def _find_gaps(
    fragments: List[BorderFragment],
    orientation: str,
) -> List[Tuple[float, float, float]]:
    """
    Find gaps between sorted fragments on the same axis.
    Returns list of (gap_start, gap_end, gap_px).
    """
    if len(fragments) < 2:
        return []

    sorted_frags = sorted(fragments, key=lambda f: f.start)
    gaps: List[Tuple[float, float, float]] = []

    # Merge overlapping fragments first to avoid false gaps
    merged: List[Tuple[float, float]] = [(sorted_frags[0].start, sorted_frags[0].end)]
    for frag in sorted_frags[1:]:
        last_start, last_end = merged[-1]
        if frag.start <= last_end + 2.0:  # 2px overlap tolerance
            merged[-1] = (last_start, max(last_end, frag.end))
        else:
            merged.append((frag.start, frag.end))

    for i in range(len(merged) - 1):
        gap_start = merged[i][1]
        gap_end = merged[i + 1][0]
        gap_px = gap_end - gap_start
        if gap_px > 0:
            gaps.append((gap_start, gap_end, gap_px))

    return gaps


def _score_horizontal_gap(
    axis_y: float,
    gap_start: float,
    gap_end: float,
    v_axis_positions: List[float],
    h_axis_positions: List[float],
) -> float:
    """
    Score a horizontal gap by checking:
    1. Whether vertical lines pass through the gap boundaries (alignment)
    2. Whether adjacent horizontal lines exist above/below (row structure)
    """
    score = 0.0

    # Signal 1: Vertical lines at or near gap boundaries
    if v_axis_positions:
        near_start = any(abs(vx - gap_start) <= AXIS_SNAP_TOLERANCE * 2 for vx in v_axis_positions)
        near_end = any(abs(vx - gap_end) <= AXIS_SNAP_TOLERANCE * 2 for vx in v_axis_positions)
        if near_start:
            score += 0.35
        if near_end:
            score += 0.35

    # Signal 2: Vertical lines exist within the gap span (column structure)
    v_in_gap = [vx for vx in v_axis_positions if gap_start < vx < gap_end]
    if v_in_gap:
        score += 0.15  # v-lines crossing the gap = likely inside a table

    # Signal 3: Nearby parallel horizontal lines (confirms row structure)
    if len(h_axis_positions) >= 2:
        h_near = [hy for hy in h_axis_positions if 5 < abs(hy - axis_y) < 200]
        if h_near:
            score += 0.15

    return min(1.0, score)


def _score_vertical_gap(
    axis_x: float,
    gap_start: float,
    gap_end: float,
    h_axis_positions: List[float],
    v_axis_positions: List[float],
) -> float:
    """
    Score a vertical gap by checking:
    1. Whether horizontal lines pass through the gap boundaries
    2. Whether adjacent vertical lines exist left/right (column structure)
    """
    score = 0.0

    if h_axis_positions:
        near_start = any(abs(hy - gap_start) <= AXIS_SNAP_TOLERANCE * 2 for hy in h_axis_positions)
        near_end = any(abs(hy - gap_end) <= AXIS_SNAP_TOLERANCE * 2 for hy in h_axis_positions)
        if near_start:
            score += 0.35
        if near_end:
            score += 0.35

    h_in_gap = [hy for hy in h_axis_positions if gap_start < hy < gap_end]
    if h_in_gap:
        score += 0.15

    if len(v_axis_positions) >= 2:
        v_near = [vx for vx in v_axis_positions if 5 < abs(vx - axis_x) < 200]
        if v_near:
            score += 0.15

    return min(1.0, score)


def _emit_audit(
    result: BorderInferenceResult,
    orientation: str,
    axis_pos: float,
    gap_start: float,
    gap_end: float,
    gap_px: float,
    score: float,
    accepted: bool,
    reject_reason: Optional[str] = None,
) -> None:
    result.audit_records.append(GapFillAuditRecord(
        orientation=orientation,
        axis_position=axis_pos,
        gap_start=gap_start,
        gap_end=gap_end,
        gap_px=gap_px,
        alignment_score=score,
        accepted=accepted,
        reject_reason=reject_reason,
    ))
