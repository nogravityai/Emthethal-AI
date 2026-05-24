"""
core/geometry/geometry_engine.py — Emthethal AI
PDF Layout Reconstruction via DBSCAN Clustering.

CRITICAL ALGORITHM CONSTRAINT:
- Primary: DBSCAN clustering on X-axis (columns) and Y-axis (rows)
- Fallback: Nearest-neighbor grouping based on sorted X/Y centroids
- FORBIDDEN: No alternative clustering methods allowed

This engine takes raw OCR bounding boxes and reconstructs table/form layouts
by identifying rows and columns from spatial coordinates.
"""

import logging
import numpy as np
from typing import List, Dict, Tuple, Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ─── Data Structures ──────────────────────────────────────────────────────────

@dataclass
class OCRWord:
    """A single OCR-detected word with its spatial coordinates."""
    text: str
    bbox: List[float]  # [x1, y1, x2, y2]
    confidence: float
    cx: float = 0.0  # center-x
    cy: float = 0.0  # center-y

    def __post_init__(self):
        if len(self.bbox) == 4:
            x1, y1, x2, y2 = self.bbox
            self.cx = (x1 + x2) / 2.0
            self.cy = (y1 + y2) / 2.0


@dataclass
class ReconstructedCell:
    """A cell within a reconstructed table grid."""
    text: str
    bbox: List[float]
    confidence: float
    row_idx: int
    col_idx: int


@dataclass
class ReconstructedTable:
    """A fully reconstructed table from geometric analysis."""
    cells: List[ReconstructedCell]
    num_rows: int
    num_cols: int
    confidence: float
    bbox: List[float]  # bounding box of entire table


# ─── DBSCAN Implementation ───────────────────────────────────────────────────

class GeometryEngine:
    """
    Reconstructs document layout from OCR bounding boxes using DBSCAN clustering.

    Strategy:
    1. Cluster Y-coordinates (cy) to identify rows
    2. Within each row cluster, cluster X-coordinates (cx) to identify columns
    3. Sort cells into a grid [row][col]

    Parameters:
    - row_eps: DBSCAN epsilon for Y-axis clustering (row detection)
    - col_eps: DBSCAN epsilon for X-axis clustering (column detection)
    - min_samples: DBSCAN min_samples (default 1 = every point can be a cluster)
    """

    def __init__(
        self,
        row_eps: float = 15.0,
        col_eps: float = 40.0,
        min_samples: int = 1,
    ):
        self.row_eps = row_eps
        self.col_eps = col_eps
        self.min_samples = min_samples

    def reconstruct_layout(
        self, ocr_words: List[OCRWord]
    ) -> List[ReconstructedTable]:
        """
        Main entry point: reconstruct tables from a list of OCR words.

        Returns a list of ReconstructedTable objects. Each represents
        a detected table region in the page.
        """
        if not ocr_words:
            logger.warning("No OCR words provided to geometry engine")
            return []

        try:
            return self._dbscan_reconstruction(ocr_words)
        except Exception as e:
            logger.warning(f"DBSCAN reconstruction failed: {e}. Falling back to nearest-neighbor.")
            return self._nearest_neighbor_fallback(ocr_words)

    def _dbscan_reconstruction(
        self, ocr_words: List[OCRWord]
    ) -> List[ReconstructedTable]:
        """
        Primary method: DBSCAN clustering.
        Step 1: Cluster by Y (rows)
        Step 2: Within each row cluster, cluster by X (columns)
        Step 3: Assemble grid
        """
        from sklearn.cluster import DBSCAN

        # ── Step 1: Cluster Y-coordinates to find rows ──
        cy_values = np.array([[w.cy] for w in ocr_words])
        row_clustering = DBSCAN(eps=self.row_eps, min_samples=self.min_samples)
        row_labels = row_clustering.fit_predict(cy_values)

        # Group words by row label
        row_groups: Dict[int, List[OCRWord]] = {}
        for word, label in zip(ocr_words, row_labels):
            if label == -1:
                # Noise point — assign to nearest row
                label = self._assign_noise_to_nearest_row(word, row_groups, ocr_words, row_labels)
            if label not in row_groups:
                row_groups[label] = []
            row_groups[label].append(word)

        # Sort rows by average Y position (top to bottom)
        sorted_row_labels = sorted(
            row_groups.keys(),
            key=lambda lbl: np.mean([w.cy for w in row_groups[lbl]])
        )

        # ── Step 2: Within each row, cluster X-coordinates for columns ──
        # First, determine global column positions from ALL words
        cx_values = np.array([[w.cx] for w in ocr_words])
        col_clustering = DBSCAN(eps=self.col_eps, min_samples=self.min_samples)
        col_labels = col_clustering.fit_predict(cx_values)

        # Build global column index mapping
        col_groups: Dict[int, List[float]] = {}
        for word, label in zip(ocr_words, col_labels):
            if label == -1:
                label = self._assign_noise_to_nearest_col(word, ocr_words, col_labels)
            if label not in col_groups:
                col_groups[label] = []
            col_groups[label].append(word.cx)

        # Sort columns by average X position (left to right)
        sorted_col_labels = sorted(
            col_groups.keys(),
            key=lambda lbl: np.mean(col_groups[lbl])
        )
        col_label_to_idx = {lbl: idx for idx, lbl in enumerate(sorted_col_labels)}

        # Build per-word column assignment
        word_col_map: Dict[int, int] = {}
        for i, (word, label) in enumerate(zip(ocr_words, col_labels)):
            if label == -1:
                label = self._assign_noise_to_nearest_col(word, ocr_words, col_labels)
            word_col_map[id(word)] = col_label_to_idx.get(label, 0)

        # ── Step 3: Assemble grid of cells ──
        num_rows = len(sorted_row_labels)
        num_cols = len(sorted_col_labels)

        cells: List[ReconstructedCell] = []
        all_x1, all_y1, all_x2, all_y2 = [], [], [], []

        for row_idx, row_label in enumerate(sorted_row_labels):
            row_words = row_groups[row_label]
            # Sort words left-to-right within the row
            row_words.sort(key=lambda w: w.cx)

            # Group words by column
            col_word_groups: Dict[int, List[OCRWord]] = {}
            for word in row_words:
                col_idx = word_col_map.get(id(word), 0)
                if col_idx not in col_word_groups:
                    col_word_groups[col_idx] = []
                col_word_groups[col_idx].append(word)

            for col_idx in range(num_cols):
                words_in_cell = col_word_groups.get(col_idx, [])
                if words_in_cell:
                    cell_text = " ".join(w.text for w in words_in_cell)
                    cell_confidence = sum(w.confidence for w in words_in_cell) / len(words_in_cell)
                    cell_bbox = [
                        min(w.bbox[0] for w in words_in_cell),
                        min(w.bbox[1] for w in words_in_cell),
                        max(w.bbox[2] for w in words_in_cell),
                        max(w.bbox[3] for w in words_in_cell),
                    ]
                else:
                    cell_text = ""
                    cell_confidence = 0.0
                    cell_bbox = [0.0, 0.0, 0.0, 0.0]

                cells.append(ReconstructedCell(
                    text=cell_text,
                    bbox=cell_bbox,
                    confidence=cell_confidence,
                    row_idx=row_idx,
                    col_idx=col_idx,
                ))

                if words_in_cell:
                    all_x1.append(cell_bbox[0])
                    all_y1.append(cell_bbox[1])
                    all_x2.append(cell_bbox[2])
                    all_y2.append(cell_bbox[3])

        # Compute overall table bounding box and confidence
        table_bbox = [
            min(all_x1) if all_x1 else 0.0,
            min(all_y1) if all_y1 else 0.0,
            max(all_x2) if all_x2 else 0.0,
            max(all_y2) if all_y2 else 0.0,
        ]
        non_empty = [c for c in cells if c.text.strip()]
        table_confidence = (
            sum(c.confidence for c in non_empty) / len(non_empty)
            if non_empty else 0.0
        )

        table = ReconstructedTable(
            cells=cells,
            num_rows=num_rows,
            num_cols=num_cols,
            confidence=table_confidence,
            bbox=table_bbox,
        )

        logger.info(
            f"DBSCAN reconstruction: {num_rows} rows × {num_cols} cols, "
            f"confidence={table_confidence:.3f}"
        )
        return [table]

    # ─── Fallback: Nearest-Neighbor Grouping ──────────────────────────────────

    def _nearest_neighbor_fallback(
        self, ocr_words: List[OCRWord]
    ) -> List[ReconstructedTable]:
        """
        Fallback strategy: nearest-neighbor grouping based on sorted X/Y centroids.

        1. Sort all words by Y centroid
        2. Group into rows: consecutive words whose Y-gap < row_eps
        3. Within each row, sort by X centroid
        4. Group into columns: consecutive words whose X-gap < col_eps
        """
        logger.info("Using nearest-neighbor fallback for layout reconstruction")

        if not ocr_words:
            return []

        # Sort by Y centroid (top to bottom)
        sorted_by_y = sorted(ocr_words, key=lambda w: w.cy)

        # Group into rows by Y proximity
        rows: List[List[OCRWord]] = [[sorted_by_y[0]]]
        for i in range(1, len(sorted_by_y)):
            prev_cy = np.mean([w.cy for w in rows[-1]])
            curr_cy = sorted_by_y[i].cy
            if abs(curr_cy - prev_cy) <= self.row_eps:
                rows[-1].append(sorted_by_y[i])
            else:
                rows.append([sorted_by_y[i]])

        # Determine column positions from ALL words sorted by X
        all_cx = sorted(set(round(w.cx, 1) for w in ocr_words))
        col_centers: List[float] = [all_cx[0]] if all_cx else []
        for i in range(1, len(all_cx)):
            if abs(all_cx[i] - col_centers[-1]) > self.col_eps:
                col_centers.append(all_cx[i])
            else:
                # Merge: update center to rolling average
                col_centers[-1] = (col_centers[-1] + all_cx[i]) / 2.0

        num_cols = max(len(col_centers), 1)

        def _find_col(cx: float) -> int:
            """Find nearest column index for a given X centroid."""
            if not col_centers:
                return 0
            dists = [abs(cx - cc) for cc in col_centers]
            return int(np.argmin(dists))

        # Build cells
        cells: List[ReconstructedCell] = []
        all_x1, all_y1, all_x2, all_y2 = [], [], [], []

        for row_idx, row_words in enumerate(rows):
            row_words.sort(key=lambda w: w.cx)

            # Group words in this row by column
            col_word_groups: Dict[int, List[OCRWord]] = {}
            for word in row_words:
                col_idx = _find_col(word.cx)
                if col_idx not in col_word_groups:
                    col_word_groups[col_idx] = []
                col_word_groups[col_idx].append(word)

            for col_idx in range(num_cols):
                words_in_cell = col_word_groups.get(col_idx, [])
                if words_in_cell:
                    cell_text = " ".join(w.text for w in words_in_cell)
                    cell_confidence = sum(w.confidence for w in words_in_cell) / len(words_in_cell)
                    cell_bbox = [
                        min(w.bbox[0] for w in words_in_cell),
                        min(w.bbox[1] for w in words_in_cell),
                        max(w.bbox[2] for w in words_in_cell),
                        max(w.bbox[3] for w in words_in_cell),
                    ]
                    all_x1.append(cell_bbox[0])
                    all_y1.append(cell_bbox[1])
                    all_x2.append(cell_bbox[2])
                    all_y2.append(cell_bbox[3])
                else:
                    cell_text = ""
                    cell_confidence = 0.0
                    cell_bbox = [0.0, 0.0, 0.0, 0.0]

                cells.append(ReconstructedCell(
                    text=cell_text,
                    bbox=cell_bbox,
                    confidence=cell_confidence,
                    row_idx=row_idx,
                    col_idx=col_idx,
                ))

        num_rows = len(rows)
        table_bbox = [
            min(all_x1) if all_x1 else 0.0,
            min(all_y1) if all_y1 else 0.0,
            max(all_x2) if all_x2 else 0.0,
            max(all_y2) if all_y2 else 0.0,
        ]
        non_empty = [c for c in cells if c.text.strip()]
        table_confidence = (
            sum(c.confidence for c in non_empty) / len(non_empty)
            if non_empty else 0.0
        )

        table = ReconstructedTable(
            cells=cells,
            num_rows=num_rows,
            num_cols=num_cols,
            confidence=table_confidence,
            bbox=table_bbox,
        )

        logger.info(
            f"Nearest-neighbor fallback: {num_rows} rows × {num_cols} cols, "
            f"confidence={table_confidence:.3f}"
        )
        return [table]

    # ─── Noise Assignment Helpers ─────────────────────────────────────────────

    def _assign_noise_to_nearest_row(
        self,
        word: OCRWord,
        row_groups: Dict[int, List[OCRWord]],
        all_words: List[OCRWord],
        labels: np.ndarray,
    ) -> int:
        """Assign a DBSCAN noise point to the nearest existing row cluster."""
        if not row_groups:
            return 0
        best_label = 0
        best_dist = float("inf")
        for label, group_words in row_groups.items():
            avg_cy = np.mean([w.cy for w in group_words])
            dist = abs(word.cy - avg_cy)
            if dist < best_dist:
                best_dist = dist
                best_label = label
        return best_label

    def _assign_noise_to_nearest_col(
        self,
        word: OCRWord,
        all_words: List[OCRWord],
        col_labels: np.ndarray,
    ) -> int:
        """Assign a DBSCAN noise point to the nearest existing column cluster."""
        valid_labels = set(l for l in col_labels if l != -1)
        if not valid_labels:
            return 0
        best_label = 0
        best_dist = float("inf")
        for label in valid_labels:
            col_words = [w for w, l in zip(all_words, col_labels) if l == label]
            avg_cx = np.mean([w.cx for w in col_words])
            dist = abs(word.cx - avg_cx)
            if dist < best_dist:
                best_dist = dist
                best_label = label
        return best_label

    # ─── Conversion to Schema Objects ─────────────────────────────────────────

    def tables_to_structure_blocks(
        self, tables: List[ReconstructedTable]
    ) -> List[dict]:
        """
        Convert ReconstructedTable objects into StructureBlock-compatible dicts
        that can be validated through the Pydantic schema.
        """
        blocks = []
        for table in tables:
            # Organize cells by row
            rows_dict: Dict[int, List[ReconstructedCell]] = {}
            for cell in table.cells:
                if cell.row_idx not in rows_dict:
                    rows_dict[cell.row_idx] = []
                rows_dict[cell.row_idx].append(cell)

            # Build row list
            table_rows = []
            for row_idx in sorted(rows_dict.keys()):
                row_cells = sorted(rows_dict[row_idx], key=lambda c: c.col_idx)
                cells_data = []
                for cell in row_cells:
                    cells_data.append({
                        "text": cell.text,
                        "value": None,
                        "confidence": round(cell.confidence, 4),
                        "bbox": [round(v, 2) for v in cell.bbox],
                    })
                if any(c["text"].strip() for c in cells_data):
                    table_rows.append({"cells": cells_data})

            if table_rows:
                # Detect headers: first row if it looks like a header
                headers = None
                first_row_texts = [c["text"] for c in table_rows[0]["cells"]]
                if all(t.strip() for t in first_row_texts):
                    headers = first_row_texts

                blocks.append({
                    "type": "table",
                    "confidence": round(table.confidence, 4),
                    "rows": table_rows,
                    "headers": headers,
                })

        return blocks


# ─── Module-Level Instance ────────────────────────────────────────────────────

geometry_engine = GeometryEngine()
