from typing import List, Tuple, Any, Dict
from app.models.schemas import BoundingBox
from app.services.fusion.models import LayoutHypothesis

class SpatialRegionIndex:
    """
    A fast 2D spatial index for querying regions that intersect a given bounding box.
    Currently implemented as a simple grid-based spatial partition for fast lookups.
    """
    def __init__(self, page_width: int, page_height: int, cell_size: int = 100):
        self.page_width = page_width
        self.page_height = page_height
        self.cell_size = cell_size
        # Dictionary mapping grid coordinate (col, row) to list of hypotheses
        self._grid: Dict[Tuple[int, int], List[LayoutHypothesis]] = {}
        self._all_regions: List[LayoutHypothesis] = []

    def _get_grid_cells(self, bbox: BoundingBox) -> List[Tuple[int, int]]:
        """Determine which grid cells a bounding box overlaps."""
        min_col = max(0, int(bbox.x1 // self.cell_size))
        max_col = int(bbox.x2 // self.cell_size)
        min_row = max(0, int(bbox.y1 // self.cell_size))
        max_row = int(bbox.y2 // self.cell_size)
        
        cells = []
        for c in range(min_col, max_col + 1):
            for r in range(min_row, max_row + 1):
                cells.append((c, r))
        return cells

    def build(self, regions: List[LayoutHypothesis]):
        """Build the spatial index from a list of layout hypotheses."""
        self._grid.clear()
        self._all_regions = regions
        for region in regions:
            cells = self._get_grid_cells(region.bbox)
            for cell in cells:
                if cell not in self._grid:
                    self._grid[cell] = []
                self._grid[cell].append(region)

    def query(self, bbox: BoundingBox) -> List[LayoutHypothesis]:
        """
        Return all regions that potentially intersect the given bounding box.
        This provides a fast O(1) broad-phase collision detection.
        """
        cells = self._get_grid_cells(bbox)
        candidates = set()
        for cell in cells:
            for region in self._grid.get(cell, []):
                candidates.add(region.hypothesis_id)
        
        # Return the actual objects
        return [r for r in self._all_regions if r.hypothesis_id in candidates]
