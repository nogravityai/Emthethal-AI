import logging
from collections import deque
from typing import List, Dict, Any, Tuple
from app.models.schemas import BoundingBox, TableTopologyEvidence, CoordinateSpace
from app.services.pipeline.pipeline_models import generate_stable_id

logger = logging.getLogger(__name__)

# ── Table candidate scoring ────────────────────────────────────────────────────
# Hard-exclude unambiguous structural containers that can never be table cells.
_HARD_EXCLUDE_TYPES = frozenset({
    "section_header", "form_title", "footer",
    "signature_block", "signature_area"
})
_TABLE_SCORE_THRESHOLD = 0.5


def _table_candidate_score(region, all_regions,
                           col_tol: float = 12.0,
                           row_tol: float = 10.0) -> float:
    """
    Score a region's likelihood of belonging to a table grid.
    Checks row alignment, column alignment, and spacing regularity
    against neighbouring regions.

    Returns a float in [0.0, 1.0].
    Hard-excludes structural containers (section headers, footers, etc.).
    """
    if getattr(region, 'region_type', None) in _HARD_EXCLUDE_TYPES:
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

    def _spacing_regularity(centroids):
        if len(centroids) < 2:
            return 0.4
        gaps = [centroids[i+1] - centroids[i] for i in range(len(centroids)-1)]
        mean_gap = sum(gaps) / len(gaps)
        if mean_gap <= 0:
            return 0.0
        variance = sum((g - mean_gap) ** 2 for g in gaps) / len(gaps)
        return 1.0 if variance / mean_gap < 0.3 else 0.4

    row_score = 0.0
    if row_peers:
        xs = sorted((r.bbox.x1 + r.bbox.x2) / 2.0 for r in row_peers)
        row_score = _spacing_regularity(xs)

    col_score = 0.0
    if col_peers:
        ys = sorted((r.bbox.y1 + r.bbox.y2) / 2.0 for r in col_peers)
        col_score = _spacing_regularity(ys)

    has_peers = 1.0 if (row_peers or col_peers) else 0.0
    return 0.4 * has_peers + 0.3 * row_score + 0.3 * col_score


class TableTopologyResolver:
    """
    Resolves layout cell boxes and detected lines into a logical grid topology.
    Translates physical DetectedBoxEvidence + DetectedLineEvidence to TableTopologyEvidence.
    Handles colspan, rowspan, and row/column alignment.
    """
    def __init__(self, overlap_threshold: float = 0.35, merge_epsilon: float = 8.0):
        self.overlap_threshold = overlap_threshold
        self.merge_epsilon = merge_epsilon

    def resolve_page_topology(
        self,
        page_number: int,
        boxes: List[Any],
        lines: List[Any],
        page_width: int,
        page_height: int
    ) -> List[TableTopologyEvidence]:
        # Only process regions/boxes where region_type is "table", "table_cell", "input_box", or "unknown"
        # [REVISED] Score-based candidate selection replaces the old whitelist.
        # Hard-excludes structural containers; uses alignment/spacing regularity score.
        table_boxes = [
            b for b in boxes
            if _table_candidate_score(b, boxes) > _TABLE_SCORE_THRESHOLD
        ]
        if not table_boxes:
            return []

        # 1. Cluster boxes into logical tables
        tables = self._cluster_boxes_into_tables(table_boxes)
        
        topology_evidence = []
        for table_idx, cluster_boxes in enumerate(tables):
            table_boxes = cluster_boxes
            table_id = f"table_{page_number}_{table_idx}"
            
            # Find the bounding box of this table
            min_x = min(b.bbox.x1 for b in table_boxes)
            min_y = min(b.bbox.y1 for b in table_boxes)
            max_x = max(b.bbox.x2 for b in table_boxes)
            max_y = max(b.bbox.y2 for b in table_boxes)
            
            # Filter lines that fall within or touch the table bounding box
            table_lines = []
            for line in lines:
                margin = 15.0
                if (min_x - margin <= line.bbox.x2 and line.bbox.x1 <= max_x + margin and
                    min_y - margin <= line.bbox.y2 and line.bbox.y1 <= max_y + margin):
                    table_lines.append(line)

            # 2. Extract grid lines
            h_lines = [l for l in table_lines if l.orientation == "horizontal"]
            v_lines = [l for l in table_lines if l.orientation == "vertical"]

            # Compute y-coordinates for rows and x-coordinates for columns
            row_coords = [min_y, max_y]
            for l in h_lines:
                row_coords.append((l.bbox.y1 + l.bbox.y2) / 2.0)
            for b in table_boxes:
                row_coords.extend([b.bbox.y1, b.bbox.y2])

            col_coords = [min_x, max_x]
            for l in v_lines:
                col_coords.append((l.bbox.x1 + l.bbox.x2) / 2.0)
            for b in table_boxes:
                col_coords.extend([b.bbox.x1, b.bbox.x2])

            # Merge coordinates that are very close
            unique_rows = self._merge_coordinates(row_coords)
            unique_cols = self._merge_coordinates(col_coords)

            # 3. Resolve spans for each box
            for box in table_boxes:
                # Row span
                matched_rows = []
                for r in range(len(unique_rows) - 1):
                    y_start = unique_rows[r]
                    y_end = unique_rows[r+1]
                    intersect = max(0.0, min(box.bbox.y2, y_end) - max(box.bbox.y1, y_start))
                    union = max(box.bbox.y2, y_end) - min(box.bbox.y1, y_start)
                    if union > 0 and (intersect / union) > self.overlap_threshold:
                        matched_rows.append(r)

                # Column span
                matched_cols = []
                for c in range(len(unique_cols) - 1):
                    x_start = unique_cols[c]
                    x_end = unique_cols[c+1]
                    intersect = max(0.0, min(box.bbox.x2, x_end) - max(box.bbox.x1, x_start))
                    union = max(box.bbox.x2, x_end) - min(box.bbox.x1, x_start)
                    if union > 0 and (intersect / union) > self.overlap_threshold:
                        matched_cols.append(c)

                # Fallback to nearest if none matched (edge case)
                if not matched_rows:
                    box_cy = (box.bbox.y1 + box.bbox.y2) / 2.0
                    dists = [abs(box_cy - (unique_rows[r] + unique_rows[r+1])/2.0) for r in range(len(unique_rows)-1)]
                    matched_rows = [dists.index(min(dists))]
                if not matched_cols:
                    box_cx = (box.bbox.x1 + box.bbox.x2) / 2.0
                    dists = [abs(box_cx - (unique_cols[c] + unique_cols[c+1])/2.0) for c in range(len(unique_cols)-1)]
                    matched_cols = [dists.index(min(dists))]

                row_idx = min(matched_rows)
                rowspan = max(matched_rows) - row_idx + 1

                col_idx = min(matched_cols)
                colspan = max(matched_cols) - col_idx + 1

                box_id = getattr(box, "stable_id", getattr(box, "cell_id", None))
                stable_id = generate_stable_id("table_topo", table_id, box_id, row_idx, col_idx)

                topology_evidence.append(TableTopologyEvidence(
                    stable_id=stable_id,
                    page_number=page_number,
                    table_id=table_id,
                    row_index=row_idx,
                    column_index=col_idx,
                    rowspan=rowspan,
                    colspan=colspan,
                    cell_id=box_id,
                    bbox=box.bbox,
                    coordinate_space=CoordinateSpace.PAGE_PIXELS
                ))

        return topology_evidence

    def _cluster_boxes_into_tables(self, boxes: List[Any]) -> List[List[Any]]:
        """
        Group boxes into spatial tables using a connected components BFS.
        """
        connections = {i: [] for i in range(len(boxes))}
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                b1 = boxes[i].bbox
                b2 = boxes[j].bbox

                v_dist = max(0.0, b2.y1 - b1.y2) if b2.y1 > b1.y2 else max(0.0, b1.y1 - b2.y2)
                h_overlap = max(0.0, min(b1.x2, b2.x2) - max(b1.x1, b2.x1))

                h_dist = max(0.0, b2.x1 - b1.x2) if b2.x1 > b1.x2 else max(0.0, b1.x1 - b2.x2)
                v_overlap = max(0.0, min(b1.y2, b2.y2) - max(b1.y1, b2.y1))

                connected = False
                avg_h = (b1.height + b2.height) / 2.0
                avg_w = (b1.width + b2.width) / 2.0

                if v_dist < 1.5 * avg_h and h_overlap > 0:
                    connected = True
                elif h_dist < 1.5 * avg_w and v_overlap > 0:
                    connected = True

                if connected:
                    connections[i].append(j)
                    connections[j].append(i)

        visited = set()
        components = []
        for i in range(len(boxes)):
            if i not in visited:
                comp = []
                queue = deque([i])
                visited.add(i)
                while queue:
                    curr = queue.popleft()
                    comp.append(boxes[curr])
                    for nbr in connections[curr]:
                        if nbr not in visited:
                            visited.add(nbr)
                            queue.append(nbr)
                components.append(comp)
        return components

    def _merge_coordinates(self, coords: List[float]) -> List[float]:
        """Merge close coordinates to build a clean logical grid."""
        if not coords:
            return []
        sorted_coords = sorted(coords)
        merged = []
        curr_sum = sorted_coords[0]
        curr_count = 1
        for c in sorted_coords[1:]:
            if c - (curr_sum / curr_count) < self.merge_epsilon:
                curr_sum += c
                curr_count += 1
            else:
                merged.append(curr_sum / curr_count)
                curr_sum = c
                curr_count = 1
        merged.append(curr_sum / curr_count)
        return merged
