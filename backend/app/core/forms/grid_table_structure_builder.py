"""
Grid / Table Structure Builder  — Phase 2 Form Understanding Layer

Primary algorithm: Spatial cell-alignment clustering (bounding-box row/column
alignment). This is the primary path because many documents (scans, photos,
rasterized PDFs) have NO detected lines.

Secondary boost: Line-intersection evidence. When horizontal/vertical lines are
detected in geometry_evidence, they validate and refine the clustering result.

Outputs LogicalTable objects consumed by SemanticFormGraphBuilder.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Data models ─────────────────────────────────────────────────────────

class LogicalCell:
    """One cell in a detected logical table."""
    __slots__ = ("row", "col", "text", "is_header", "bbox", "region_id")

    def __init__(
        self,
        row: int,
        col: int,
        text: str,
        is_header: bool,
        bbox: Tuple[float, float, float, float],  # (x1, y1, x2, y2)
        region_id: Optional[str] = None,
    ) -> None:
        self.row = row
        self.col = col
        self.text = text
        self.is_header = is_header
        self.bbox = bbox
        self.region_id = region_id

    def __repr__(self) -> str:  # pragma: no cover
        return f"LogicalCell(r={self.row}, c={self.col}, text={self.text!r})"


class LogicalTable:
    """A detected logical table with row/column structure."""

    def __init__(
        self,
        table_id: str,
        bbox: Tuple[float, float, float, float],
        cells: List[LogicalCell],
    ) -> None:
        self.table_id = table_id
        self.bbox = bbox        # (x1, y1, x2, y2) of the full table
        self.cells = cells

    # Convenience helpers
    def header_cells(self) -> List[LogicalCell]:
        return [c for c in self.cells if c.is_header]

    def data_cells(self) -> List[LogicalCell]:
        return [c for c in self.cells if not c.is_header]

    def col_header(self, col: int) -> Optional[str]:
        """Return the header text for a given column index, or None."""
        for c in self.cells:
            if c.col == col and c.is_header:
                return c.text
        return None

    def row_count(self) -> int:
        return max((c.row for c in self.cells), default=0) + 1

    def col_count(self) -> int:
        return max((c.col for c in self.cells), default=0) + 1

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"LogicalTable(id={self.table_id!r}, "
            f"{self.row_count()}r×{self.col_count()}c, "
            f"{len(self.cells)} cells)"
        )


# ── Table scoring helper ────────────────────────────────────────────────────

_HARD_EXCLUDE_TABLE = frozenset({
    "section_header", "form_title", "footer",
    "signature_block", "signature_area",
})
_TABLE_SCORE_THRESHOLD = 0.45


def _table_candidate_score(
    region: Any,
    all_regions: List[Any],
    col_tol: float = 15.0,
    row_tol: float = 12.0,
) -> float:
    """
    Score how likely a region belongs to a table grid.
    Uses row/column alignment and spacing regularity of neighbouring regions.
    Returns float in [0.0, 1.0].
    """
    rtype = getattr(region, "region_type", None)
    if rtype in _HARD_EXCLUDE_TABLE:
        return 0.0

    cx = (region.bbox.x1 + region.bbox.x2) / 2.0
    cy = (region.bbox.y1 + region.bbox.y2) / 2.0

    row_peers = [
        r for r in all_regions
        if r is not region
        and abs((r.bbox.y1 + r.bbox.y2) / 2.0 - cy) <= row_tol
    ]
    col_peers = [
        r for r in all_regions
        if r is not region
        and abs((r.bbox.x1 + r.bbox.x2) / 2.0 - cx) <= col_tol
    ]

    def _regularity(coords: List[float]) -> float:
        if len(coords) < 2:
            return 0.4
        coords = sorted(coords)
        gaps = [coords[i + 1] - coords[i] for i in range(len(coords) - 1)]
        mean_g = sum(gaps) / len(gaps)
        if mean_g <= 0:
            return 0.0
        variance = sum((g - mean_g) ** 2 for g in gaps) / len(gaps)
        return 1.0 if variance / mean_g < 0.35 else 0.4

    row_score = _regularity([(r.bbox.x1 + r.bbox.x2) / 2.0 for r in row_peers]) if row_peers else 0.0
    col_score = _regularity([(r.bbox.y1 + r.bbox.y2) / 2.0 for r in col_peers]) if col_peers else 0.0
    has_peers = 1.0 if (row_peers or col_peers) else 0.0

    return 0.4 * has_peers + 0.3 * row_score + 0.3 * col_score


# ── GridTableStructureBuilder ───────────────────────────────────────────────

class GridTableStructureBuilder:
    """
    Detects table grids from document regions.

    Algorithm (two-step):
      Step 1 — Primary: Spatial cell-alignment clustering.
        Groups regions into rows and columns based on centroid proximity.
        Works on any document type, even when no lines are detected.

      Step 2 — Secondary boost: Line-intersection validation.
        When horizontal/vertical lines are available, their intersections
        form a grid lattice that validates and corrects Step 1 assignments.
    """

    def __init__(
        self,
        row_tol: float = 10.0,
        col_tol: float = 12.0,
        min_cluster_size: int = 3,
        line_epsilon: float = 8.0,
    ) -> None:
        self.row_tol = row_tol
        self.col_tol = col_tol
        self.min_cluster_size = min_cluster_size
        self.line_epsilon = line_epsilon

    # ── Public entry point ────────────────────────────────────────────

    def build(
        self,
        regions: List[Any],
        page_w: float,
        page_h: float,
        lines: Optional[List[Any]] = None,
    ) -> List[LogicalTable]:
        """
        Build LogicalTable objects from detected regions.

        Args:
            regions:  List of geometry region objects with .bbox (x1,y1,x2,y2)
                      and optional .region_type string.
            page_w:   Page width in pixels.
            page_h:   Page height in pixels.
            lines:    Optional list of detected line objects (horizontal/vertical).
                      Used as secondary boost ONLY — tables are detected without them.

        Returns:
            List of LogicalTable objects.
        """
        # Filter to table-candidate regions
        candidates = [
            r for r in regions
            if _table_candidate_score(r, regions) > _TABLE_SCORE_THRESHOLD
        ]
        if not candidates:
            return []

        # Step 1: primary spatial clustering
        tables = self._cluster_into_tables(candidates)

        # Step 2: optional line-intersection boost
        if lines:
            tables = self._boost_with_lines(tables, lines)

        logger.info(
            "GridTableStructureBuilder: found %d logical table(s) from %d candidate regions.",
            len(tables), len(candidates)
        )
        return tables

    # ── Step 1: Spatial alignment clustering ────────────────────────

    def _cluster_into_tables(self, regions: List[Any]) -> List[LogicalTable]:
        """Group regions into tables via connected-component BFS, then assign row/col."""
        n = len(regions)
        if n == 0:
            return []

        # Build adjacency: two regions are connected if they share a row or column
        adj: Dict[int, List[int]] = {i: [] for i in range(n)}
        for i in range(n):
            for j in range(i + 1, n):
                ri = regions[i]
                rj = regions[j]
                cy_i = (ri.bbox.y1 + ri.bbox.y2) / 2.0
                cy_j = (rj.bbox.y1 + rj.bbox.y2) / 2.0
                cx_i = (ri.bbox.x1 + ri.bbox.x2) / 2.0
                cx_j = (rj.bbox.x1 + rj.bbox.x2) / 2.0
                if abs(cy_i - cy_j) <= self.row_tol or abs(cx_i - cx_j) <= self.col_tol:
                    adj[i].append(j)
                    adj[j].append(i)

        # BFS to find connected components
        visited = [False] * n
        components: List[List[int]] = []
        for start in range(n):
            if visited[start]:
                continue
            queue = [start]
            visited[start] = True
            comp: List[int] = []
            while queue:
                curr = queue.pop()
                comp.append(curr)
                for nb in adj[curr]:
                    if not visited[nb]:
                        visited[nb] = True
                        queue.append(nb)
            if len(comp) >= self.min_cluster_size:
                components.append(comp)

        tables: List[LogicalTable] = []
        for t_idx, comp in enumerate(components):
            comp_regions = [regions[i] for i in comp]
            table = self._assign_row_col(comp_regions, t_idx)
            if table:
                tables.append(table)

        return tables

    def _assign_row_col(
        self, regions: List[Any], table_idx: int
    ) -> Optional[LogicalTable]:
        """Assign row/col indices to regions using centroid clustering."""
        if not regions:
            return None

        # Cluster Y centroids into rows
        cy_vals = [(r.bbox.y1 + r.bbox.y2) / 2.0 for r in regions]
        row_labels = self._cluster_1d(cy_vals, self.row_tol)

        # Cluster X centroids into columns
        cx_vals = [(r.bbox.x1 + r.bbox.x2) / 2.0 for r in regions]
        col_labels = self._cluster_1d(cx_vals, self.col_tol)

        # Identify header row (row 0 = top-most) and header col
        # For RTL forms, the rightmost column (highest x) is usually the label column
        all_rows = sorted(set(row_labels))
        all_cols = sorted(set(col_labels), reverse=True)  # RTL: right = col 0

        row_rank = {r: i for i, r in enumerate(all_rows)}
        col_rank = {c: i for i, c in enumerate(all_cols)}

        cells: List[LogicalCell] = []
        x1_all = [r.bbox.x1 for r in regions]
        y1_all = [r.bbox.y1 for r in regions]
        x2_all = [r.bbox.x2 for r in regions]
        y2_all = [r.bbox.y2 for r in regions]

        for i, reg in enumerate(regions):
            row_idx = row_rank[row_labels[i]]
            col_idx = col_rank[col_labels[i]]
            # First data row (row_idx == 0) treated as header
            is_header = (row_idx == 0)
            text = getattr(reg, "text", "") or ""
            region_id = getattr(reg, "stable_id", None)
            cells.append(LogicalCell(
                row=row_idx,
                col=col_idx,
                text=text,
                is_header=is_header,
                bbox=(reg.bbox.x1, reg.bbox.y1, reg.bbox.x2, reg.bbox.y2),
                region_id=region_id,
            ))

        table_bbox = (
            min(x1_all), min(y1_all),
            max(x2_all), max(y2_all),
        )
        table_id = f"lt_{table_idx:03d}"
        return LogicalTable(table_id=table_id, bbox=table_bbox, cells=cells)

    @staticmethod
    def _cluster_1d(values: List[float], tol: float) -> List[int]:
        """Assign cluster labels to 1-D values using greedy merging."""
        sorted_idx = sorted(range(len(values)), key=lambda i: values[i])
        labels = [0] * len(values)
        cluster_id = 0
        cluster_center = values[sorted_idx[0]]
        labels[sorted_idx[0]] = cluster_id

        for idx in sorted_idx[1:]:
            v = values[idx]
            if abs(v - cluster_center) <= tol:
                labels[idx] = cluster_id
                # Update cluster center as running mean
                members = [values[j] for j in sorted_idx if labels[j] == cluster_id]
                cluster_center = sum(members) / len(members)
            else:
                cluster_id += 1
                cluster_center = v
                labels[idx] = cluster_id

        return labels

    # ── Step 2: Line-intersection boost ───────────────────────────

    def _boost_with_lines(
        self,
        tables: List[LogicalTable],
        lines: List[Any],
    ) -> List[LogicalTable]:
        """
        Use detected lines to validate/refine table cell assignments.
        Lines are SECONDARY evidence — they adjust assignments, never create tables.
        """
        h_lines = [l for l in lines if getattr(l, "orientation", "") == "horizontal"]
        v_lines = [l for l in lines if getattr(l, "orientation", "") == "vertical"]

        if not h_lines or not v_lines:
            return tables  # no intersections possible; return clustering result unchanged

        # Compute intersection y-coords and x-coords
        h_ys = self._merge_coords([((l.bbox.y1 + l.bbox.y2) / 2.0) for l in h_lines])
        v_xs = self._merge_coords([((l.bbox.x1 + l.bbox.x2) / 2.0) for l in v_lines])

        if len(h_ys) < 2 or len(v_xs) < 2:
            return tables

        refined: List[LogicalTable] = []
        for table in tables:
            # Re-snap each cell's row/col to the nearest lattice coordinate
            new_cells: List[LogicalCell] = []
            for cell in table.cells:
                cell_cy = (cell.bbox[1] + cell.bbox[3]) / 2.0
                cell_cx = (cell.bbox[0] + cell.bbox[2]) / 2.0

                best_row = min(range(len(h_ys)), key=lambda i: abs(h_ys[i] - cell_cy))
                best_col = min(range(len(v_xs)), key=lambda i: abs(v_xs[i] - cell_cx))

                # Only apply if improvement is within epsilon
                if (abs(h_ys[best_row] - cell_cy) < self.line_epsilon and
                        abs(v_xs[best_col] - cell_cx) < self.line_epsilon):
                    new_cells.append(LogicalCell(
                        row=best_row,
                        col=best_col,
                        text=cell.text,
                        is_header=(best_row == 0),
                        bbox=cell.bbox,
                        region_id=cell.region_id,
                    ))
                else:
                    new_cells.append(cell)

            refined.append(LogicalTable(
                table_id=table.table_id,
                bbox=table.bbox,
                cells=new_cells,
            ))

        return refined

    def _merge_coords(self, coords: List[float]) -> List[float]:
        """Merge close coordinates to build a clean logical grid."""
        if not coords:
            return []
        sorted_coords = sorted(coords)
        merged = []
        curr_sum = sorted_coords[0]
        curr_count = 1
        for c in sorted_coords[1:]:
            if c - (curr_sum / curr_count) < self.line_epsilon:
                curr_sum += c
                curr_count += 1
            else:
                merged.append(curr_sum / curr_count)
                curr_sum = c
                curr_count = 1
        merged.append(curr_sum / curr_count)
        return merged
