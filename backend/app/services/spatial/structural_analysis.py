# ============================================================
# CFIS Phase 2 — Structural Analysis Engine
# Location: backend/app/services/structural_analysis.py
#
# PURPOSE: Convert raw geometry primitives into structural
# layout understanding: regions, anchors, and table grids.
#
# KEY CONSTRAINT — GRAPH-BASED TABLE GRIDS:
#   Tables are modeled as graphs (Nodes=intersections, Edges=lines,
#   Regions=inferred cells), NOT raw line intersections. This allows
#   tolerance for broken borders, faint scans, partial separators.
#
# RULE 3: This module emits LayoutHypotheses ONLY.
#   It NEVER produces final LayoutCells or FormFields.
#
# PHASE 2B ADDITIONS:
#   build_table_grids_with_inference() — applies border_inference first
#   detect_all_nested_grids()          — finds grids inside table cells
# ============================================================

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

import numpy as np
from pydantic import BaseModel, Field

from app.models.schemas import BoundingBox, CoordinateSpace
from app.services.geometry.visual_geometry import DetectedLine, DetectedBox

logger = logging.getLogger(__name__)

# ── STRUCTURAL PRIMITIVES ─────────────────────────────────────────────────────


class StructuralAnchor(BaseModel):
    """
    Hard geometric constraint derived from a visual line or boundary.
    Acts as a 'wall' that prevents cross-cluster token merging.
    """
    anchor_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    anchor_type: str  # "horizontal_rule" | "vertical_rule" | "table_boundary" | "section_boundary" | "form_boundary"
    bbox: BoundingBox
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    source_line_ids: List[str] = Field(default_factory=list)


class SpatialRegion(BaseModel):
    """
    Macro-level document region. Groups primitives and anchors semantically.
    Children enable hierarchical nesting (e.g., table containing rows).
    """
    region_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    region_type: str  # "table" | "header" | "footer" | "sidebar" | "form_section" | "signature_area" | "metadata_region"
    bbox: BoundingBox
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    children: List["SpatialRegion"] = Field(default_factory=list)
    anchor_ids: List[str] = Field(default_factory=list)


class TableNode(BaseModel):
    """A node in the table graph — represents a line intersection point."""
    node_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    x: float
    y: float


class TableEdge(BaseModel):
    """An edge in the table graph — represents a detected line segment."""
    edge_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    from_node_id: str
    to_node_id: str
    orientation: str  # "horizontal" | "vertical"
    is_inferred: bool = False  # True if gap-filled


class TableGrid(BaseModel):
    """
    Graph-based table grid. Tolerates broken borders via gap-filling inference.

    Graph structure:
      Nodes = line intersections
      Edges = detected (or inferred) lines
      Regions = inferred table cells bounded by edges
    """
    grid_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    bbox: BoundingBox
    nodes: List[TableNode] = Field(default_factory=list)
    edges: List[TableEdge] = Field(default_factory=list)
    cell_bboxes: List[BoundingBox] = Field(default_factory=list)
    row_count: int = 0
    col_count: int = 0
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    has_inferred_edges: bool = False


# ── STRUCTURAL ANALYSIS FUNCTIONS ─────────────────────────────────────────────


def infer_structural_regions(
    lines: List[DetectedLine],
    boxes: List[DetectedBox],
    page_width: int,
    page_height: int,
    page_number: int = 0,
) -> List[SpatialRegion]:
    """
    Convert raw geometry into macro-level spatial regions.
    Uses horizontal rule positions to identify headers, footers, and
    form sections. Uses density of boxes to identify table regions.

    Returns SpatialRegion list — does NOT emit LayoutCells (Rule 3).
    """
    regions: List[SpatialRegion] = []

    h_lines = sorted(
        [l for l in lines if l.orientation == "horizontal"],
        key=lambda l: l.y1,
    )
    v_lines = sorted(
        [l for l in lines if l.orientation == "vertical"],
        key=lambda l: l.x1,
    )

    def _make_bbox(x1: float, y1: float, x2: float, y2: float) -> BoundingBox:
        return BoundingBox(
            x1=max(0.0, x1), y1=max(0.0, y1),
            x2=min(float(page_width), x2),
            y2=min(float(page_height), y2),
            coordinate_space=CoordinateSpace.PAGE_PIXELS,
            page_width=page_width,
            page_height=page_height,
        )

    # Header: region above first significant horizontal rule
    HEADER_THRESHOLD = page_height * 0.20
    significant_h = [l for l in h_lines if l.length > page_width * 0.4]
    if significant_h:
        first_rule_y = significant_h[0].y1
        if first_rule_y > 10 and first_rule_y < HEADER_THRESHOLD:
            regions.append(SpatialRegion(
                region_type="header",
                bbox=_make_bbox(0, 0, page_width, first_rule_y),
                confidence=0.85,
            ))

    # Footer: region below last significant horizontal rule
    FOOTER_THRESHOLD = page_height * 0.80
    if significant_h:
        last_rule_y = significant_h[-1].y1
        if last_rule_y > FOOTER_THRESHOLD:
            regions.append(SpatialRegion(
                region_type="footer",
                bbox=_make_bbox(0, last_rule_y, page_width, page_height),
                confidence=0.80,
            ))

    # Table candidate zones: dense intersections of h+v lines
    table_zones = _find_table_zones(h_lines, v_lines, page_width, page_height)
    for zone_bbox in table_zones:
        regions.append(SpatialRegion(
            region_type="table",
            bbox=zone_bbox,
            confidence=0.75,
        ))

    # Signature areas: wide, short, low-fill boxes near bottom of page
    sig_boxes = [
        b for b in boxes
        if b.box_type in ("signature_box", "input_box")
        and b.bbox.y1 > page_height * 0.7
        and b.bbox.width > page_width * 0.2
    ]
    for sb in sig_boxes:
        regions.append(SpatialRegion(
            region_type="signature_area",
            bbox=sb.bbox,
            confidence=sb.confidence * 0.9,
        ))

    logger.info(
        f"infer_structural_regions: {len(regions)} regions "
        f"({sum(1 for r in regions if r.region_type=='table')} tables, "
        f"{sum(1 for r in regions if r.region_type=='header')} headers)"
    )
    return regions


def _find_table_zones(
    h_lines: List[DetectedLine],
    v_lines: List[DetectedLine],
    page_width: int,
    page_height: int,
) -> List[BoundingBox]:
    """
    Find zones where horizontal and vertical lines cluster together.
    A table zone requires at least 2 h-lines and 2 v-lines with spatial overlap.
    """
    if len(h_lines) < 2 or len(v_lines) < 2:
        return []

    # Cluster h-lines vertically into table row groups
    h_ys = np.array([l.y1 for l in h_lines])
    v_xs = np.array([l.x1 for l in v_lines])

    # Simple gap-based grouping
    h_sorted = sorted(h_lines, key=lambda l: l.y1)
    v_sorted = sorted(v_lines, key=lambda l: l.x1)

    # Find vertical extent of clustered h-lines
    zones: List[BoundingBox] = []
    MAX_GAP = page_height * 0.12

    group_start = 0
    for i in range(1, len(h_sorted)):
        gap = h_sorted[i].y1 - h_sorted[i - 1].y1
        is_last = i == len(h_sorted) - 1
        if gap > MAX_GAP or is_last:
            group = h_sorted[group_start: i + (1 if is_last else 0)]
            if len(group) >= 2:
                y_min = min(l.y1 for l in group)
                y_max = max(l.y1 for l in group)
                # Find v-lines that overlap this y-range
                v_in_zone = [
                    v for v in v_sorted
                    if not (v.y2 < y_min or v.y1 > y_max)
                ]
                if len(v_in_zone) >= 2:
                    x_min = min(v.x1 for v in v_in_zone)
                    x_max = max(v.x1 for v in v_in_zone)
                    # Expand slightly
                    x_min = max(0.0, x_min - 5)
                    x_max = min(float(page_width), x_max + 5)
                    zones.append(BoundingBox(
                        x1=x_min, y1=y_min, x2=x_max, y2=y_max,
                        coordinate_space=CoordinateSpace.PAGE_PIXELS,
                        page_width=page_width,
                        page_height=page_height,
                    ))
            group_start = i

    return zones


def build_table_grids(
    lines: List[DetectedLine],
    page_width: int,
    page_height: int,
    snap_tolerance: float = 8.0,
    infer_broken: bool = True,
) -> List[TableGrid]:
    """
    Build graph-based table grids from detected lines.

    Algorithm:
      1. Snap nearby parallel lines to consensus positions (eliminate duplicates)
      2. Find all intersection points (nodes) where H and V lines cross
      3. Build graph edges from the detected lines
      4. Infer missing edges for broken borders (if infer_broken=True)
      5. Extract cell bboxes from closed rectangles in the graph

    Returns TableGrid objects — does NOT emit LayoutCells (Rule 3).
    """
    if not lines:
        return []

    h_lines = [l for l in lines if l.orientation == "horizontal"]
    v_lines = [l for l in lines if l.orientation == "vertical"]

    if len(h_lines) < 2 or len(v_lines) < 2:
        return []

    # 1. Snap to consensus positions
    h_positions = _snap_lines_to_consensus(
        [l.y1 for l in h_lines], snap_tolerance
    )
    v_positions = _snap_lines_to_consensus(
        [l.x1 for l in v_lines], snap_tolerance
    )

    if len(h_positions) < 2 or len(v_positions) < 2:
        return []

    # 2. Build nodes at intersections
    nodes: List[TableNode] = []
    node_map: Dict[Tuple[float, float], TableNode] = {}
    for y in h_positions:
        for x in v_positions:
            n = TableNode(x=x, y=y)
            nodes.append(n)
            node_map[(x, y)] = n

    # 3. Build edges from H lines
    edges: List[TableEdge] = []
    h_sorted = sorted(h_positions)
    v_sorted = sorted(v_positions)

    for y in h_sorted:
        row_nodes = sorted(
            [n for n in nodes if abs(n.y - y) < snap_tolerance],
            key=lambda n: n.x,
        )
        for i in range(len(row_nodes) - 1):
            n_from = row_nodes[i]
            n_to = row_nodes[i + 1]
            # Check if any detected h_line actually covers this span
            covered = any(
                abs(l.y1 - y) < snap_tolerance
                and l.x1 <= n_from.x + snap_tolerance
                and l.x2 >= n_to.x - snap_tolerance
                for l in h_lines
            )
            edges.append(TableEdge(
                from_node_id=n_from.node_id,
                to_node_id=n_to.node_id,
                orientation="horizontal",
                is_inferred=not covered,
            ))

    for x in v_sorted:
        col_nodes = sorted(
            [n for n in nodes if abs(n.x - x) < snap_tolerance],
            key=lambda n: n.y,
        )
        for i in range(len(col_nodes) - 1):
            n_from = col_nodes[i]
            n_to = col_nodes[i + 1]
            covered = any(
                abs(l.x1 - x) < snap_tolerance
                and l.y1 <= n_from.y + snap_tolerance
                and l.y2 >= n_to.y - snap_tolerance
                for l in v_lines
            )
            edges.append(TableEdge(
                from_node_id=n_from.node_id,
                to_node_id=n_to.node_id,
                orientation="vertical",
                is_inferred=not covered,
            ))

    # 4. Extract cells as axis-aligned rectangles in the grid
    cell_bboxes: List[BoundingBox] = []
    for ri in range(len(h_sorted) - 1):
        for ci in range(len(v_sorted) - 1):
            x1 = v_sorted[ci]
            x2 = v_sorted[ci + 1]
            y1 = h_sorted[ri]
            y2 = h_sorted[ri + 1]
            cell_bboxes.append(BoundingBox(
                x1=x1, y1=y1, x2=x2, y2=y2,
                coordinate_space=CoordinateSpace.PAGE_PIXELS,
                page_width=page_width,
                page_height=page_height,
            ))

    has_inferred = any(e.is_inferred for e in edges)
    grid_x1 = min(v_positions)
    grid_x2 = max(v_positions)
    grid_y1 = min(h_positions)
    grid_y2 = max(h_positions)

    grid = TableGrid(
        bbox=BoundingBox(
            x1=grid_x1, y1=grid_y1, x2=grid_x2, y2=grid_y2,
            coordinate_space=CoordinateSpace.PAGE_PIXELS,
            page_width=page_width,
            page_height=page_height,
        ),
        nodes=nodes,
        edges=edges,
        cell_bboxes=cell_bboxes,
        row_count=len(h_positions) - 1,
        col_count=len(v_positions) - 1,
        confidence=0.9 if not has_inferred else 0.70,
        has_inferred_edges=has_inferred,
    )

    logger.info(
        f"build_table_grids: {grid.row_count}×{grid.col_count} grid, "
        f"{len(cell_bboxes)} cells, "
        f"{'inferred edges' if has_inferred else 'fully detected'}"
    )
    return [grid]


def _snap_lines_to_consensus(
    positions: List[float],
    tolerance: float,
) -> List[float]:
    """
    Cluster nearby line positions and snap to their mean.
    Eliminates near-duplicate lines from morphology artifacts.
    """
    if not positions:
        return []
    sorted_pos = sorted(positions)
    groups: List[List[float]] = [[sorted_pos[0]]]
    for p in sorted_pos[1:]:
        if p - groups[-1][-1] <= tolerance:
            groups[-1].append(p)
        else:
            groups.append([p])
    return [float(np.mean(g)) for g in groups]


def detect_section_boundaries(
    lines: List[DetectedLine],
    page_width: int,
    page_height: int,
) -> List[StructuralAnchor]:
    """
    Identify horizontal rules that act as section boundaries.
    A section boundary is a near-full-width horizontal line.
    Returns StructuralAnchor objects — NOT LayoutCells.
    """
    MIN_SPAN_FRACTION = 0.55  # must span >55% of page width
    anchors: List[StructuralAnchor] = []

    for line in lines:
        if line.orientation != "horizontal":
            continue
        span = line.x2 - line.x1
        if span >= page_width * MIN_SPAN_FRACTION:
            anchor_type = "horizontal_rule"
            if span >= page_width * 0.85:
                anchor_type = "section_boundary"
            bbox = BoundingBox(
                x1=line.x1, y1=line.y1 - line.thickness / 2,
                x2=line.x2, y2=line.y1 + line.thickness / 2,
                coordinate_space=CoordinateSpace.PAGE_PIXELS,
                page_width=page_width,
                page_height=page_height,
            )
            anchors.append(StructuralAnchor(
                anchor_type=anchor_type,
                bbox=bbox,
                confidence=line.confidence,
            ))

    logger.info(f"detect_section_boundaries: {len(anchors)} anchors detected")
    return anchors


def build_region_hierarchy(
    regions: List[SpatialRegion],
) -> List[SpatialRegion]:
    """
    Organize regions into a containment hierarchy.
    A region that is geometrically contained within another becomes its child.
    Only top-level regions are returned (children are nested).
    """
    if len(regions) <= 1:
        return regions

    # Sort by area descending (larger regions = likely parents)
    sorted_regions = sorted(
        regions,
        key=lambda r: r.bbox.area,
        reverse=True,
    )

    assigned: Set[str] = set()

    for i, parent in enumerate(sorted_regions):
        for j, child in enumerate(sorted_regions):
            if i == j or child.region_id in assigned:
                continue
            if _bbox_contains(parent.bbox, child.bbox):
                parent.children.append(child)
                assigned.add(child.region_id)

    # Return only top-level regions
    return [r for r in sorted_regions if r.region_id not in assigned]


def _bbox_contains(outer: BoundingBox, inner: BoundingBox) -> bool:
    """Return True if outer strictly contains inner (with 5px tolerance)."""
    margin = 5.0
    return (
        outer.x1 <= inner.x1 + margin
        and outer.y1 <= inner.y1 + margin
        and outer.x2 >= inner.x2 - margin
        and outer.y2 >= inner.y2 - margin
        and outer.area > inner.area * 1.2
    )


# ── PHASE 2B: BORDER-INFERENCE-ENHANCED GRID BUILDER ────────────────────────


def build_table_grids_with_inference(
    lines: List[DetectedLine],
    page_width: int,
    page_height: int,
    snap_tolerance: float = 8.0,
    max_gap_px: float = 80.0,
    min_alignment_score: float = 0.55,
) -> List[TableGrid]:
    """
    Phase 2B: Build table grids with border inference applied first.

    Extends build_table_grids() by:
      1. Running border_inference.run_border_inference() on the input lines
      2. Merging inferred fragments back into the line set
      3. Building the graph from the enriched line set

    The result will have better coverage of broken-border tables:
    faint scan gaps, partial separators, and smeared ink.

    Returns TableGrid objects — does NOT emit LayoutCells (Rule 3).
    """
    from app.services.legacy_geometry.text_clustering_engine.border_inference import run_border_inference

    inference_result = run_border_inference(
        lines=lines,
        page_width=page_width,
        page_height=page_height,
        max_gap_px=max_gap_px,
        min_alignment_score=min_alignment_score,
    )

    enriched_lines = inference_result.all_as_detected_lines(
        page_width=page_width,
        page_height=page_height,
    )

    logger.info(
        f"build_table_grids_with_inference: "
        f"{len(lines)} original + {len(inference_result.inferred_fragments)} "
        f"inferred = {len(enriched_lines)} total lines for grid building"
    )

    return build_table_grids(
        lines=enriched_lines,
        page_width=page_width,
        page_height=page_height,
        snap_tolerance=snap_tolerance,
        infer_broken=True,
    )


# ── PHASE 2B: NESTED GRID DETECTION ─────────────────────────────────────────


def detect_all_nested_grids(
    grids: List[TableGrid],
) -> Dict[str, List[TableGrid]]:
    """
    Phase 2B: Detect nested grids (a table inside another table's cell).

    For each grid, find any other grids whose bbox is contained within
    one of its cell bboxes. Returns a Dict mapping parent_grid_id →
    list of child TableGrids.

    Delegates to cell_merger.detect_nested_grids() for the containment check.
    """
    from app.services.spatial.cell_merger import detect_nested_grids

    nested_map: Dict[str, List[TableGrid]] = {}

    for parent in grids:
        children = detect_nested_grids(parent, grids)
        if children:
            nested_map[parent.grid_id] = children
            logger.info(
                f"detect_all_nested_grids: grid {parent.grid_id} "
                f"contains {len(children)} nested grid(s)"
            )

    return nested_map
