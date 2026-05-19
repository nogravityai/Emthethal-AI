import math
from typing import Tuple
from app.models.schemas import BoundingBox

def compute_iou(box_a: BoundingBox, box_b: BoundingBox) -> float:
    """Compute Intersection over Union for two bounding boxes."""
    dx = min(box_a.x2, box_b.x2) - max(box_a.x1, box_b.x1)
    dy = min(box_a.y2, box_b.y2) - max(box_a.y1, box_b.y1)
    if (dx > 0) and (dy > 0):
        intersection = dx * dy
        area_a = (box_a.x2 - box_a.x1) * (box_a.y2 - box_a.y1)
        area_b = (box_b.x2 - box_b.x1) * (box_b.y2 - box_b.y1)
        union = area_a + area_b - intersection
        return intersection / union if union > 0 else 0.0
    return 0.0

def compute_overlap_ratio(token_box: BoundingBox, region_box: BoundingBox) -> float:
    """
    Compute how much of the token is inside the region.
    Returns intersection_area / token_area.
    """
    dx = min(token_box.x2, region_box.x2) - max(token_box.x1, region_box.x1)
    dy = min(token_box.y2, region_box.y2) - max(token_box.y1, region_box.y1)
    if (dx > 0) and (dy > 0):
        intersection = dx * dy
        token_area = (token_box.x2 - token_box.x1) * (token_box.y2 - token_box.y1)
        return intersection / token_area if token_area > 0 else 0.0
    return 0.0

def get_center(box: BoundingBox) -> Tuple[float, float]:
    return (box.x1 + box.x2) / 2.0, (box.y1 + box.y2) / 2.0

def center_inside(token_box: BoundingBox, region_box: BoundingBox) -> bool:
    """Check if the center point of the token is inside the region."""
    cx, cy = get_center(token_box)
    return (region_box.x1 <= cx <= region_box.x2) and (region_box.y1 <= cy <= region_box.y2)

def center_distance(box_a: BoundingBox, box_b: BoundingBox) -> float:
    """Compute Euclidean distance between the centers of two boxes."""
    cax, cay = get_center(box_a)
    cbx, cby = get_center(box_b)
    return math.hypot(cax - cbx, cay - cby)

def edge_distance(box_a: BoundingBox, box_b: BoundingBox) -> float:
    """Compute the minimum distance between the edges of two boxes."""
    dx = max(0.0, max(box_a.x1, box_b.x1) - min(box_a.x2, box_b.x2))
    dy = max(0.0, max(box_a.y1, box_b.y1) - min(box_a.y2, box_b.y2))
    return math.hypot(dx, dy)
