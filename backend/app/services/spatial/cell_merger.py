# ============================================================
# CFIS Phase 2B — Cell Merger
# Location: backend/app/services/cell_merger.py
#
# PURPOSE: Detect and resolve merged cells (colspan/rowspan) in
# table grids. Real institutional forms frequently use cells that
# span multiple columns (headers) or multiple rows (labels).
#
# ALGORITHM:
#   1. Build an occupancy matrix for the inferred grid
#   2. Detect missing interior borders (edges with is_inferred=True)
#   3. Cluster adjacent cells separated only by inferred edges
#   4. Assign colspan/rowspan to each resulting MergedCell
#   5. Rebuild the canonical cell list with merged spans
#
# RULE 3: Outputs are MergedCell objects and updated TableGrid.
#   They become table_cell LayoutHypotheses in the registry.
# ============================================================

from __future__ import annotations

import logging
import uuid
from typing import Dict, List, Optional, Set, Tuple

import numpy as np
from pydantic import BaseModel, Field

from app.models.schemas import BoundingBox, CoordinateSpace
from app.services.spatial.structural_analysis import TableEdge, TableGrid, TableNode

logger = logging.getLogger(__name__)

# ── MERGED CELL TYPES ─────────────────────────────────────────────────────────


class MergedCell(BaseModel):
    """
    A canonical table cell that may span multiple grid rows/columns.

    Attributes:
        row_start / row_end: 0-indexed row range (inclusive)
        col_start / col_end: 0-indexed column range (inclusive)
        rowspan: number of rows spanned (1 = no merge)
        colspan: number of columns spanned (1 = no merge)
        is_merged: True if rowspan>1 or colspan>1
        bbox: union bounding box of all merged sub-cells
        inferred_borders: IDs of inferred edges that were dissolved by this merge
    """
    cell_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:10])
    row_start: int
    row_end: int
    col_start: int
    col_end: int
    rowspan: int = 1
    colspan: int = 1
    is_merged: bool = False
    bbox: BoundingBox
    inferred_borders: List[str] = Field(default_factory=list)  # dissolved edge IDs
    confidence: float = Field(ge=0.0, le=1.0, default=0.85)


class MergedGridResult(BaseModel):
    """Result of resolve_merged_cells() for one TableGrid."""
    grid_id: str
    original_cell_count: int
    merged_cell_count: int
    merged_cells: List[MergedCell] = Field(default_factory=list)
    dissolved_edge_ids: List[str] = Field(default_factory=list)
    has_merged_cells: bool = False


# ── PUBLIC API ────────────────────────────────────────────────────────────────


def resolve_merged_cells(
    grid: TableGrid,
    max_span: int = 6,
) -> MergedGridResult:
    """
    Detect and resolve merged cells in a TableGrid.

    A cell merge is identified when the interior border between two
    adjacent cells is flagged as is_inferred=True (meaning it was not
    actually detected, only inferred by position). In this case, the
    two cells should be treated as a single merged cell.

    Returns a MergedGridResult with the final canonical cell list.
    The caller should use merged_cells to generate table_cell hypotheses.
    """
    rows = grid.row_count
    cols = grid.col_count

    if rows == 0 or cols == 0 or len(grid.cell_bboxes) == 0:
        return MergedGridResult(
            grid_id=grid.grid_id,
            original_cell_count=0,
            merged_cell_count=0,
        )

    # Build lookup: (row, col) → BoundingBox
    cell_matrix: Dict[Tuple[int, int], BoundingBox] = {}
    idx = 0
    for r in range(rows):
        for c in range(cols):
            if idx < len(grid.cell_bboxes):
                cell_matrix[(r, c)] = grid.cell_bboxes[idx]
            idx += 1

    # Build adjacency info: which interior edges are inferred (= merge candidates)
    node_map = {n.node_id: n for n in grid.nodes}
    h_sorted = sorted(set(n.y for n in grid.nodes))
    v_sorted = sorted(set(n.x for n in grid.nodes))

    # Map node positions to (row_idx, col_idx)
    def _row_of(y: float) -> int:
        diffs = [abs(y - hy) for hy in h_sorted]
        return int(np.argmin(diffs))

    def _col_of(x: float) -> int:
        diffs = [abs(x - vx) for vx in v_sorted]
        return int(np.argmin(diffs))

    # Collect inferred interior edges (not boundary edges)
    inferred_h_edges: Set[Tuple[int, int]] = set()  # (row, col) → gap between row and row+1 at col
    inferred_v_edges: Set[Tuple[int, int]] = set()  # (row, col) → gap between col and col+1 at row

    dissolved_edge_ids: List[str] = []

    for edge in grid.edges:
        if not edge.is_inferred:
            continue
        n_from = node_map.get(edge.from_node_id)
        n_to = node_map.get(edge.to_node_id)
        if not n_from or not n_to:
            continue

        if edge.orientation == "horizontal":
            row_idx = _row_of(n_from.y)
            col_from = _col_of(min(n_from.x, n_to.x))
            col_to = _col_of(max(n_from.x, n_to.x))
            # Interior H edge = boundary between (row_idx-1, col) and (row_idx, col)
            if 0 < row_idx < len(h_sorted) - 1:
                for c in range(col_from, col_to):
                    inferred_h_edges.add((row_idx, c))
                dissolved_edge_ids.append(edge.edge_id)

        else:  # vertical
            col_idx = _col_of(n_from.x)
            row_from = _row_of(min(n_from.y, n_to.y))
            row_to = _row_of(max(n_from.y, n_to.y))
            # Interior V edge = boundary between (row, col_idx-1) and (row, col_idx)
            if 0 < col_idx < len(v_sorted) - 1:
                for r in range(row_from, row_to):
                    inferred_v_edges.add((r, col_idx))
                dissolved_edge_ids.append(edge.edge_id)

    # Union-Find to cluster cells that should be merged
    parent: Dict[Tuple[int, int], Tuple[int, int]] = {
        (r, c): (r, c) for r in range(rows) for c in range(cols)
    }

    def _find(cell: Tuple[int, int]) -> Tuple[int, int]:
        while parent[cell] != cell:
            parent[cell] = parent[parent[cell]]
            cell = parent[cell]
        return cell

    def _union(a: Tuple[int, int], b: Tuple[int, int]) -> None:
        ra, rb = _find(a), _find(b)
        if ra != rb:
            parent[rb] = ra

    # Merge cells separated by inferred horizontal edges (row merges)
    for (row_idx, col) in inferred_h_edges:
        if row_idx > 0 and col < cols:
            above = (row_idx - 1, col)
            below = (row_idx, col)
            if above in parent and below in parent:
                _union(above, below)

    # Merge cells separated by inferred vertical edges (col merges)
    for (row, col_idx) in inferred_v_edges:
        if col_idx > 0 and row < rows:
            left = (row, col_idx - 1)
            right = (row, col_idx)
            if left in parent and right in parent:
                _union(left, right)

    # Group cells by their root
    clusters: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}
    for r in range(rows):
        for c in range(cols):
            root = _find((r, c))
            clusters.setdefault(root, []).append((r, c))

    # Build MergedCell for each cluster
    merged_cells: List[MergedCell] = []
    pw = grid.bbox.page_width
    ph = grid.bbox.page_height

    for root, members in clusters.items():
        r_min = min(m[0] for m in members)
        r_max = max(m[0] for m in members)
        c_min = min(m[1] for m in members)
        c_max = max(m[1] for m in members)
        rowspan = r_max - r_min + 1
        colspan = c_max - c_min + 1

        # Union bbox of all member cells
        bboxes = [cell_matrix[m] for m in members if m in cell_matrix]
        if not bboxes:
            continue

        x1 = min(b.x1 for b in bboxes)
        y1 = min(b.y1 for b in bboxes)
        x2 = max(b.x2 for b in bboxes)
        y2 = max(b.y2 for b in bboxes)

        # Collect dissolved edge IDs relevant to this cell cluster
        cell_dissolved = [
            eid for eid in dissolved_edge_ids
        ] if len(members) > 1 else []

        # Cap span to max_span
        rowspan = min(rowspan, max_span)
        colspan = min(colspan, max_span)

        merged_cells.append(MergedCell(
            row_start=r_min,
            row_end=r_max,
            col_start=c_min,
            col_end=c_max,
            rowspan=rowspan,
            colspan=colspan,
            is_merged=(rowspan > 1 or colspan > 1),
            bbox=BoundingBox(
                x1=x1, y1=y1, x2=x2, y2=y2,
                coordinate_space=CoordinateSpace.PAGE_PIXELS,
                page_width=pw,
                page_height=ph,
            ),
            inferred_borders=cell_dissolved,
            confidence=0.90 if (rowspan == 1 and colspan == 1) else 0.75,
        ))

    # Sort by reading order (top-left → bottom-right)
    merged_cells.sort(key=lambda c: (c.row_start, c.col_start))

    merged_count = sum(1 for c in merged_cells if c.is_merged)
    logger.info(
        f"resolve_merged_cells: grid={grid.grid_id} "
        f"{rows}×{cols} → {len(merged_cells)} cells "
        f"({merged_count} merged, "
        f"{len(dissolved_edge_ids)} edges dissolved)"
    )

    return MergedGridResult(
        grid_id=grid.grid_id,
        original_cell_count=rows * cols,
        merged_cell_count=len(merged_cells),
        merged_cells=merged_cells,
        dissolved_edge_ids=dissolved_edge_ids,
        has_merged_cells=merged_count > 0,
    )


def detect_nested_grids(
    parent_grid: TableGrid,
    all_grids: List[TableGrid],
) -> List[TableGrid]:
    """
    Identify which grids from all_grids are geometrically contained
    inside cells of parent_grid. Returns the nested child grids.

    A nested grid is one whose bbox is fully contained within one
    of the parent_grid's cell_bboxes.
    """
    nested: List[TableGrid] = []
    for candidate in all_grids:
        if candidate.grid_id == parent_grid.grid_id:
            continue
        for cell_bbox in parent_grid.cell_bboxes:
            if _bbox_contained(candidate.bbox, cell_bbox, margin=10.0):
                nested.append(candidate)
                logger.debug(
                    f"detect_nested_grids: grid {candidate.grid_id} "
                    f"nested inside grid {parent_grid.grid_id}"
                )
                break
    return nested


def _bbox_contained(
    inner: BoundingBox,
    outer: BoundingBox,
    margin: float = 5.0,
) -> bool:
    """Return True if inner is geometrically contained within outer."""
    return (
        inner.x1 >= outer.x1 - margin
        and inner.y1 >= outer.y1 - margin
        and inner.x2 <= outer.x2 + margin
        and inner.y2 <= outer.y2 + margin
        and inner.area < outer.area * 0.85
    )
