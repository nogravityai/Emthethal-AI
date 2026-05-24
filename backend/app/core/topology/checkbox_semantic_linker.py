import logging
import math
from typing import List, Dict, Any, Tuple, Optional
from app.models.schemas import BoundingBox, CoordinateSpace

logger = logging.getLogger(__name__)

class CheckboxSemanticLinker:
    """
    Binds visual checkboxes to their correct semantic text labels.
    Uses a weighted scoring model to rank candidate text labels for each checkbox.
    Weights:
      - Same visual row / baseline overlap: +50
      - Inside same region: +40
      - Reading direction alignment: +30
      - Euclidean distance: Low negative penalty (-0.05 * distance)
      - Crossing border/grid line: -100 penalty
    """
    def __init__(self, is_arabic: bool = True):
        self.is_arabic = is_arabic

    def link_checkboxes(
        self,
        checkboxes: List[Any],
        tokens: List[Any],
        regions: List[Any],
        lines: List[Any]
    ) -> Dict[str, str]:
        """
        Links each checkbox to its best text label.
        Returns a dictionary mapping checkbox_id -> text_label_string.
        """
        linked_labels: Dict[str, str] = {}
        if not checkboxes or not tokens:
            return linked_labels

        for cb in checkboxes:
            cb_id = getattr(cb, "stable_id", getattr(cb, "cell_id", None))
            cb_bbox = cb.bbox
            cb_cx = (cb_bbox.x1 + cb_bbox.x2) / 2.0
            cb_cy = (cb_bbox.y1 + cb_bbox.y2) / 2.0

            best_token = None
            best_score = -999.0

            for tok in tokens:
                tok_bbox = tok.bbox
                tok_cx = (tok_bbox.x1 + tok_bbox.x2) / 2.0
                tok_cy = (tok_bbox.y1 + tok_bbox.y2) / 2.0

                score = 0.0

                # 1. Logical cell and row matching (Semantic grid)
                cb_logical_row = getattr(cb, "logical_row_id", None)
                tok_logical_row = getattr(tok, "logical_row_id", None)
                cb_logical_cell = getattr(cb, "logical_cell_id", None)
                tok_logical_cell = getattr(tok, "logical_cell_id", None)

                if cb_logical_cell and tok_logical_cell and cb_logical_cell == tok_logical_cell:
                    score += 150.0
                elif cb_logical_row and tok_logical_row and cb_logical_row == tok_logical_row:
                    score += 100.0

                # 2. Baseline overlap (Same visual row)
                v_overlap = max(0.0, min(cb_bbox.y2, tok_bbox.y2) - max(cb_bbox.y1, tok_bbox.y1))
                min_h = min(cb_bbox.height, tok_bbox.height)
                row_overlap_ratio = v_overlap / min_h if min_h > 0 else 0.0
                if row_overlap_ratio > 0.5:
                    score += 50.0
                elif row_overlap_ratio > 0.1:
                    score += 20.0

                # 3. Inside same region
                for reg in regions:
                    if self._is_contained_in_region(cb_bbox, reg.bbox) and self._is_contained_in_region(tok_bbox, reg.bbox):
                        score += 40.0
                        break

                # 4. Reading direction alignment (Arabic RTL priority)
                if self.is_arabic:
                    if cb_bbox.x1 > tok_bbox.x2:  # Label is to the left of checkbox (RTL flow)
                        score += 40.0
                    elif cb_bbox.x2 < tok_bbox.x1:  # Label is to the right of checkbox
                        score += 10.0
                else:
                    if cb_bbox.x2 < tok_bbox.x1:  # Label is to the right of checkbox (LTR flow)
                        score += 40.0
                    elif cb_bbox.x1 > tok_bbox.x2:  # Label is to the left of checkbox
                        score += 10.0

                # 5. Euclidean distance (Low negative weight)
                dist = math.hypot(cb_cx - tok_cx, cb_cy - tok_cy)
                score -= 0.01 * dist

                # 6. Crossing border/grid line penalty
                if self._crosses_any_line(cb_cx, cb_cy, tok_cx, tok_cy, lines):
                    score -= 200.0

                if score > best_score:
                    best_score = score
                    best_token = tok

            # Minimum score threshold to prevent linking random distant text
            if best_token and best_score > 10.0:
                linked_labels[cb_id] = best_token.text
                logger.info(f"Linked checkbox {cb_id[:8]} -> '{best_token.text}' score={best_score:.2f}")

        return linked_labels

    def _is_contained_in_region(self, inner: BoundingBox, region: BoundingBox) -> bool:
        """True if inner box is mostly contained within region box."""
        ix1 = max(inner.x1, region.x1)
        iy1 = max(inner.y1, region.y1)
        ix2 = min(inner.x2, region.x2)
        iy2 = min(inner.y2, region.y2)
        
        if ix2 <= ix1 or iy2 <= iy1:
            return False
            
        inter_area = (ix2 - ix1) * (iy2 - iy1)
        return (inter_area / inner.area) > 0.85

    def _crosses_any_line(
        self,
        x1: float, y1: float,
        x2: float, y2: float,
        lines: List[Any]
    ) -> bool:
        """Check if segment (x1, y1) -> (x2, y2) crosses any horizontal or vertical line."""
        for line in lines:
            lx1, ly1, lx2, ly2 = line.bbox.x1, line.bbox.y1, line.bbox.x2, line.bbox.y2
            
            if line.orientation == "vertical":
                # Line is vertical, so it has x-coordinate lx = lx1 ~= lx2
                lx = (lx1 + lx2) / 2.0
                # Segment crosses vertical line if lx is between x1 and x2
                if min(x1, x2) <= lx <= max(x1, x2):
                    # And they overlap vertically
                    if max(y1, y2) >= min(ly1, ly2) and min(y1, y2) <= max(ly1, ly2):
                        return True
            elif line.orientation == "horizontal":
                ly = (ly1 + ly2) / 2.0
                if min(y1, y2) <= ly <= max(y1, y2):
                    if max(x1, x2) >= min(lx1, lx2) and min(x1, x2) <= max(lx1, lx2):
                        return True
        return False
