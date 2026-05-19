# ============================================================
# CFIS Phase 2 — Geometry Debugger
# Location: backend/app/services/geometry_debugger.py
#
# PURPOSE: Mandatory visual debugging infrastructure.
# Must be implemented BEFORE complex fusion logic.
# Renders all geometry layers (lines, anchors, grids, boxes,
# hypotheses, fusion decisions, coordinate traces) onto page images.
#
# PERFORMANCE: Canvas rendering only (OpenCV/NumPy).
# No SVG, no browser-side rendering for large datasets.
# ============================================================

from __future__ import annotations

import io
import logging
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image
from pydantic import BaseModel, Field

from app.services.coordinate_trace import CoordinateTransformTrace
from app.services.fusion.hypothesis_engine import HypothesisRegistry, LayoutHypothesis
from app.services.spatial.structural_analysis import (
    StructuralAnchor,
    SpatialRegion,
    TableGrid,
)
from app.services.geometry.visual_geometry import DetectedBox, DetectedLine

logger = logging.getLogger(__name__)

# ── COLOR PALETTE ─────────────────────────────────────────────────────────────
# BGR tuples for OpenCV drawing

COLORS = {
    "h_line":           (255, 120, 0),    # light blue
    "v_line":           (255, 60, 0),     # darker blue
    "checkbox":         (0, 220, 0),      # green
    "input_box":        (0, 180, 120),    # teal
    "signature_box":    (0, 140, 200),    # orange-ish
    "image_region":     (100, 100, 200),  # purple
    "anchor_section":   (0, 0, 255),      # red (section boundaries)
    "anchor_rule":      (0, 80, 200),     # dark red
    "region_table":     (200, 0, 200),    # magenta
    "region_header":    (0, 200, 200),    # yellow-ish
    "region_footer":    (100, 200, 100),  # light green
    "region_signature": (200, 100, 0),    # indigo
    "grid_edge":        (0, 255, 200),    # cyan-green
    "grid_edge_infer":  (0, 180, 100),    # dashed simulation
    "grid_node":        (0, 255, 255),    # yellow
    "grid_cell":        (0, 200, 255),    # gold
    "hyp_accepted":     (0, 255, 0),      # bright green
    "hyp_rejected":     (0, 0, 150),      # dark red
    "trace_arrow":      (255, 200, 0),    # cyan
    "text_label":       (255, 255, 255),  # white
    "text_shadow":      (0, 0, 0),        # black
}


# ── GEOMETRY DEBUG SNAPSHOT ───────────────────────────────────────────────────


class GeometryDebugSnapshot(BaseModel):
    """
    Full capture of the geometry pipeline state for a single page.
    Passed to renderer functions to produce debug overlays.

    Phase 2B additions:
      - border_audit: gap-fill audit records from border_inference
      - merged_cells: MergedCell list from cell_merger
    """
    page_number: int = 0
    source_dpi: float = 200.0
    page_width_px: int = 0
    page_height_px: int = 0

    # Layer 1: Visual Geometry
    detected_lines: List[DetectedLine] = Field(default_factory=list)
    detected_boxes: List[DetectedBox] = Field(default_factory=list)

    # Layer 2: Structural Analysis
    anchors: List[StructuralAnchor] = Field(default_factory=list)
    regions: List[SpatialRegion] = Field(default_factory=list)
    grids: List[TableGrid] = Field(default_factory=list)

    # Layer 3: Hypothesis Engine
    hypotheses: List[LayoutHypothesis] = Field(default_factory=list)

    # Layer 4: Coordinate Traces
    coordinate_traces: List[CoordinateTransformTrace] = Field(default_factory=list)

    # Phase 2B: Border inference + merged cells (optional)
    border_audit: List[dict] = Field(default_factory=list)   # GapFillAuditRecord dicts
    merged_cells: List[dict] = Field(default_factory=list)   # MergedCell dicts

    # Metadata
    processing_time_ms: Optional[float] = None

    class Config:
        arbitrary_types_allowed = True


# ── RENDERING UTILITIES ───────────────────────────────────────────────────────


def _pil_to_cv(pil_image: Image.Image) -> np.ndarray:
    arr = np.array(pil_image.convert("RGB"))
    return arr[:, :, ::-1].copy()  # RGB → BGR


def _cv_to_pil(cv_image: np.ndarray) -> Image.Image:
    rgb = cv_image[:, :, ::-1]
    return Image.fromarray(rgb)


def _label(
    img: np.ndarray,
    text: str,
    x: int, y: int,
    color: Tuple[int, int, int] = COLORS["text_label"],
    scale: float = 0.45,
    thickness: int = 1,
) -> None:
    """Draw a text label with a drop-shadow for readability."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    # Shadow
    cv2.putText(img, text, (x + 1, y + 1), font, scale,
                COLORS["text_shadow"], thickness + 1, cv2.LINE_AA)
    # Foreground
    cv2.putText(img, text, (x, y), font, scale,
                color, thickness, cv2.LINE_AA)


# ── PRIMARY RENDER FUNCTIONS ──────────────────────────────────────────────────


def render_geometry_debug(
    pil_image: Image.Image,
    snapshot: GeometryDebugSnapshot,
    layers: Optional[List[str]] = None,
) -> Image.Image:
    """
    Master debug renderer. Overlays all geometry layers onto the source image.

    Args:
        pil_image: Original page image (PAGE_PIXELS resolution)
        snapshot: GeometryDebugSnapshot containing all geometry data
        layers: Optional filter list. If None, all layers are rendered.
                Valid values: "lines", "boxes", "anchors", "regions",
                              "grids", "hypotheses",
                              "border_gaps", "merged_cells"  ← Phase 2B

    Returns:
        Annotated PIL Image with all requested layers overlaid.
    """
    cv_img = _pil_to_cv(pil_image)
    all_layers = layers or [
        "lines", "boxes", "anchors", "regions", "grids", "hypotheses",
        "border_gaps", "merged_cells",
    ]

    if "lines" in all_layers:
        cv_img = _draw_lines(cv_img, snapshot.detected_lines)

    if "boxes" in all_layers:
        cv_img = _draw_boxes(cv_img, snapshot.detected_boxes)

    if "anchors" in all_layers:
        cv_img = _draw_anchors(cv_img, snapshot.anchors)

    if "regions" in all_layers:
        cv_img = _draw_regions(cv_img, snapshot.regions)

    if "grids" in all_layers:
        cv_img = _draw_grid_graph(cv_img, snapshot.grids)

    if "hypotheses" in all_layers:
        cv_img = _draw_hypotheses(cv_img, snapshot.hypotheses)

    # Phase 2B layers
    if "border_gaps" in all_layers and snapshot.border_audit:
        cv_img = _draw_border_audit(cv_img, snapshot.border_audit)

    if "merged_cells" in all_layers and snapshot.merged_cells:
        cv_img = _draw_merged_cells(cv_img, snapshot.merged_cells)

    return _cv_to_pil(cv_img)


def render_hypothesis_overlay(
    pil_image: Image.Image,
    hypotheses: List[LayoutHypothesis],
    show_rejected: bool = True,
) -> Image.Image:
    """
    Render hypothesis boxes with fusion score labels.
    Accepted → bright green. Rejected → dark red (if show_rejected).
    """
    cv_img = _pil_to_cv(pil_image)
    cv_img = _draw_hypotheses(cv_img, hypotheses, show_rejected=show_rejected)
    return _cv_to_pil(cv_img)


def render_grid_graph(
    pil_image: Image.Image,
    grids: List[TableGrid],
) -> Image.Image:
    """
    Render the graph-based table grid: nodes (intersection points),
    edges (lines — solid=detected, dashed=inferred), and cell boundaries.
    """
    cv_img = _pil_to_cv(pil_image)
    cv_img = _draw_grid_graph(cv_img, grids)
    return _cv_to_pil(cv_img)


def render_anchor_overlay(
    pil_image: Image.Image,
    anchors: List[StructuralAnchor],
    regions: Optional[List[SpatialRegion]] = None,
) -> Image.Image:
    """
    Render structural anchors (section boundaries, horizontal rules)
    and spatial regions (header, footer, table zones).
    """
    cv_img = _pil_to_cv(pil_image)
    cv_img = _draw_anchors(cv_img, anchors)
    if regions:
        cv_img = _draw_regions(cv_img, regions)
    return _cv_to_pil(cv_img)


def render_border_inference(
    pil_image: Image.Image,
    audit_records: List[dict],
) -> Image.Image:
    """
    Phase 2B: Render border-inference gap-fill decisions.
    Green ticks = accepted gaps (filled). Red marks = rejected gaps.
    """
    cv_img = _pil_to_cv(pil_image)
    cv_img = _draw_border_audit(cv_img, audit_records)
    return _cv_to_pil(cv_img)


def render_merged_cells(
    pil_image: Image.Image,
    merged_cells: List[dict],
) -> Image.Image:
    """
    Phase 2B: Render merged cell bboxes with rowspan/colspan labels.
    Merged cells are shown in orange; unmerged cells in light gray.
    """
    cv_img = _pil_to_cv(pil_image)
    cv_img = _draw_merged_cells(cv_img, merged_cells)
    return _cv_to_pil(cv_img)


def render_radio_groups(
    pil_image: Image.Image,
    hypotheses: List[LayoutHypothesis],
) -> Image.Image:
    """
    Phase 2B: Render radio_group hypotheses with alignment axis labels.
    """
    cv_img = _pil_to_cv(pil_image)
    radio_hyps = [h for h in hypotheses if h.hypothesis_type == "radio_group"]
    COLOR_RADIO = (0, 165, 255)  # orange in BGR
    for hyp in radio_hyps:
        x1, y1 = int(hyp.bbox.x1), int(hyp.bbox.y1)
        x2, y2 = int(hyp.bbox.x2), int(hyp.bbox.y2)
        cv2.rectangle(cv_img, (x1, y1), (x2, y2), COLOR_RADIO, 2)
        label = f"radio ({hyp.fusion_score:.2f})"
        if hyp.text_content:
            label += f" '{hyp.text_content[:12]}'"
        _label(cv_img, label, x1, y1 - 6, COLOR_RADIO, scale=0.42)
    return _cv_to_pil(cv_img)


# ── INTERNAL LAYER DRAWING ────────────────────────────────────────────────────


def _draw_lines(
    img: np.ndarray,
    lines: List[DetectedLine],
) -> np.ndarray:
    """Draw detected lines. Horizontal=light-blue, Vertical=darker-blue."""
    for line in lines:
        color = COLORS["h_line"] if line.orientation == "horizontal" else COLORS["v_line"]
        thickness = max(1, min(4, int(line.thickness * 0.5)))
        pt1 = (int(line.x1), int(line.y1))
        pt2 = (int(line.x2), int(line.y2))
        cv2.line(img, pt1, pt2, color, thickness, cv2.LINE_AA)
    return img


def _draw_boxes(
    img: np.ndarray,
    boxes: List[DetectedBox],
) -> np.ndarray:
    """Draw detected boxes colored by box_type."""
    type_colors = {
        "checkbox":      COLORS["checkbox"],
        "input_box":     COLORS["input_box"],
        "signature_box": COLORS["signature_box"],
        "image_region":  COLORS["image_region"],
        "table_cell":    COLORS["grid_cell"],
    }
    for box in boxes:
        color = type_colors.get(box.box_type, COLORS["checkbox"])
        x1, y1, x2, y2 = int(box.bbox.x1), int(box.bbox.y1), int(box.bbox.x2), int(box.bbox.y2)
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        label = f"{box.box_type} {box.confidence:.2f}"
        _label(img, label, x1, max(y1 - 4, 10), color)
    return img


def _draw_anchors(
    img: np.ndarray,
    anchors: List[StructuralAnchor],
) -> np.ndarray:
    """Draw structural anchors as thick horizontal/vertical bars."""
    for anchor in anchors:
        color = (
            COLORS["anchor_section"]
            if anchor.anchor_type == "section_boundary"
            else COLORS["anchor_rule"]
        )
        x1, y1, x2, y2 = (
            int(anchor.bbox.x1), int(anchor.bbox.y1),
            int(anchor.bbox.x2), int(anchor.bbox.y2),
        )
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 3)
        _label(img, anchor.anchor_type, x1, y1 - 5, color, scale=0.4)
    return img


def _draw_regions(
    img: np.ndarray,
    regions: List[SpatialRegion],
) -> np.ndarray:
    """Draw spatial regions with semi-transparent overlay and label."""
    type_colors = {
        "table":          COLORS["region_table"],
        "header":         COLORS["region_header"],
        "footer":         COLORS["region_footer"],
        "signature_area": COLORS["region_signature"],
        "form_section":   COLORS["anchor_rule"],
        "sidebar":        COLORS["image_region"],
        "metadata_region": COLORS["grid_node"],
    }
    overlay = img.copy()
    for region in regions:
        color = type_colors.get(region.region_type, COLORS["region_table"])
        x1, y1 = int(region.bbox.x1), int(region.bbox.y1)
        x2, y2 = int(region.bbox.x2), int(region.bbox.y2)
        cv2.rectangle(overlay, (x1, y1), (x2, y2), color, cv2.FILLED)
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 3)
        label = f"{region.region_type} ({region.confidence:.2f})"
        _label(img, label, x1 + 5, y1 + 20, color, scale=0.55)
        for child in region.children:
            cx1, cy1 = int(child.bbox.x1), int(child.bbox.y1)
            cx2, cy2 = int(child.bbox.x2), int(child.bbox.y2)
            cv2.rectangle(img, (cx1, cy1), (cx2, cy2), color, 1)
    cv2.addWeighted(overlay, 0.15, img, 0.85, 0, img)
    return img


def _draw_grid_graph(
    img: np.ndarray,
    grids: List[TableGrid],
) -> np.ndarray:
    """
    Draw graph-based table grids:
      - Cell boundaries (gold)
      - Detected edges (solid cyan-green)
      - Inferred edges (dashed lighter green)
      - Intersection nodes (yellow dots)
    """
    for grid in grids:
        node_map = {n.node_id: n for n in grid.nodes}
        for cell_bbox in grid.cell_bboxes:
            cv2.rectangle(
                img,
                (int(cell_bbox.x1), int(cell_bbox.y1)),
                (int(cell_bbox.x2), int(cell_bbox.y2)),
                COLORS["grid_cell"], 1,
            )
        for edge in grid.edges:
            n_from = node_map.get(edge.from_node_id)
            n_to = node_map.get(edge.to_node_id)
            if not n_from or not n_to:
                continue
            pt1 = (int(n_from.x), int(n_from.y))
            pt2 = (int(n_to.x), int(n_to.y))
            color = COLORS["grid_edge_infer"] if edge.is_inferred else COLORS["grid_edge"]
            thickness = 1 if edge.is_inferred else 2
            cv2.line(img, pt1, pt2, color, thickness)
            if edge.is_inferred:
                _draw_dashed_line(img, pt1, pt2, color)
        for node in grid.nodes:
            cv2.circle(img, (int(node.x), int(node.y)), 4, COLORS["grid_node"], -1)
        label = f"grid {grid.row_count}×{grid.col_count} ({grid.confidence:.2f})"
        _label(img, label, int(grid.bbox.x1), int(grid.bbox.y1) - 8,
               COLORS["grid_node"], scale=0.5)
    return img


def _draw_hypotheses(
    img: np.ndarray,
    hypotheses: List[LayoutHypothesis],
    show_rejected: bool = True,
) -> np.ndarray:
    """Draw hypothesis bounding boxes with type + fusion score labels."""
    for hyp in hypotheses:
        if not hyp.accepted and not show_rejected:
            continue
        color = COLORS["hyp_accepted"] if hyp.accepted else COLORS["hyp_rejected"]
        thickness = 2 if hyp.accepted else 1
        x1, y1 = int(hyp.bbox.x1), int(hyp.bbox.y1)
        x2, y2 = int(hyp.bbox.x2), int(hyp.bbox.y2)
        cv2.rectangle(img, (x1, y1), (x2, y2), color, thickness)
        label = f"{hyp.hypothesis_type[:8]} {hyp.fusion_score:.2f}"
        _label(img, label, x1, y2 + 12, color, scale=0.40)
    return img


def _draw_border_audit(
    img: np.ndarray,
    audit_records: List[dict],
) -> np.ndarray:
    """
    Phase 2B: Draw border-inference gap-fill decisions.
    Accepted gaps → bright green tick marks.
    Rejected gaps → small red X marks.
    Each mark is placed at the midpoint of the gap.
    """
    COLOR_ACCEPTED = (0, 255, 60)    # bright green
    COLOR_REJECTED = (0, 40, 220)    # red

    for rec in audit_records:
        try:
            orientation = rec.get("orientation", "horizontal")
            axis = float(rec.get("axis_position", 0))
            gap_s = float(rec.get("gap_start", 0))
            gap_e = float(rec.get("gap_end", 0))
            accepted = bool(rec.get("accepted", False))
            score = float(rec.get("alignment_score", 0))

            mid = (gap_s + gap_e) / 2.0
            if orientation == "horizontal":
                cx, cy = int(mid), int(axis)
            else:
                cx, cy = int(axis), int(mid)

            color = COLOR_ACCEPTED if accepted else COLOR_REJECTED
            size = 6

            if accepted:
                # Draw a small tick (checkmark-like)
                cv2.line(img, (cx - size, cy), (cx, cy + size), color, 2)
                cv2.line(img, (cx, cy + size), (cx + size * 2, cy - size), color, 2)
                _label(img, f"{score:.2f}", cx + 4, cy - 4, color, scale=0.35)
            else:
                # Draw a small X
                cv2.line(img, (cx - size, cy - size), (cx + size, cy + size), color, 1)
                cv2.line(img, (cx + size, cy - size), (cx - size, cy + size), color, 1)
        except (KeyError, TypeError, ValueError):
            continue

    return img


def _draw_merged_cells(
    img: np.ndarray,
    merged_cells: List[dict],
) -> np.ndarray:
    """
    Phase 2B: Draw merged cell bboxes with rowspan/colspan labels.
    Merged cells (span > 1) are drawn in orange with span label.
    """
    COLOR_MERGED = (0, 140, 255)    # orange (BGR)
    COLOR_NORMAL = (180, 180, 180)  # light gray

    for cell in merged_cells:
        try:
            bbox = cell.get("bbox", {})
            x1 = int(float(bbox.get("x1", 0)))
            y1 = int(float(bbox.get("y1", 0)))
            x2 = int(float(bbox.get("x2", 0)))
            y2 = int(float(bbox.get("y2", 0)))
            rowspan = int(cell.get("rowspan", 1))
            colspan = int(cell.get("colspan", 1))
            is_merged = bool(cell.get("is_merged", False))

            color = COLOR_MERGED if is_merged else COLOR_NORMAL
            thickness = 2 if is_merged else 1
            cv2.rectangle(img, (x1, y1), (x2, y2), color, thickness)

            if is_merged:
                label = f"{rowspan}r×{colspan}c"
                _label(img, label, x1 + 3, y1 + 14, color, scale=0.45)
        except (KeyError, TypeError, ValueError):
            continue

    return img


def _draw_dashed_line(
    img: np.ndarray,
    pt1: Tuple[int, int],
    pt2: Tuple[int, int],
    color: Tuple[int, int, int],
    dash_length: int = 8,
    gap_length: int = 6,
) -> None:
    """Draw a dashed line between two points."""
    x1, y1 = pt1
    x2, y2 = pt2
    dx = x2 - x1
    dy = y2 - y1
    length = max(1, int((dx**2 + dy**2) ** 0.5))
    steps = length // (dash_length + gap_length)
    for i in range(steps):
        t_start = i * (dash_length + gap_length) / length
        t_end = (i * (dash_length + gap_length) + dash_length) / length
        t_end = min(t_end, 1.0)
        sx = int(x1 + dx * t_start)
        sy = int(y1 + dy * t_start)
        ex = int(x1 + dx * t_end)
        ey = int(y1 + dy * t_end)
        cv2.line(img, (sx, sy), (ex, ey), color, 1)


# ── SNAPSHOT SERIALIZATION ────────────────────────────────────────────────────


def snapshot_to_dict(snapshot: GeometryDebugSnapshot) -> dict:
    """Serialize a GeometryDebugSnapshot to a JSON-compatible dict."""
    accepted_gaps = sum(1 for r in snapshot.border_audit if r.get("accepted"))
    merged_count = sum(1 for c in snapshot.merged_cells if c.get("is_merged"))
    return {
        "page_number": snapshot.page_number,
        "page_size": f"{snapshot.page_width_px}×{snapshot.page_height_px}",
        "source_dpi": snapshot.source_dpi,
        "layers": {
            "lines": len(snapshot.detected_lines),
            "boxes": len(snapshot.detected_boxes),
            "anchors": len(snapshot.anchors),
            "regions": len(snapshot.regions),
            "grids": len(snapshot.grids),
            "hypotheses": {
                "total": len(snapshot.hypotheses),
                "accepted": sum(1 for h in snapshot.hypotheses if h.accepted),
                "rejected": sum(1 for h in snapshot.hypotheses if not h.accepted),
            },
            # Phase 2B
            "border_gaps": {
                "total": len(snapshot.border_audit),
                "accepted": accepted_gaps,
                "rejected": len(snapshot.border_audit) - accepted_gaps,
            },
            "merged_cells": {
                "total": len(snapshot.merged_cells),
                "merged": merged_count,
            },
        },
        "coordinate_traces": [str(t) for t in snapshot.coordinate_traces],
        "processing_time_ms": snapshot.processing_time_ms,
    }

