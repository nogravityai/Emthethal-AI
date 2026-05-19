"""
TASK-P3-13A — Structural Fingerprint Engine

Computes a deterministic, scale-invariant structural fingerprint of a document.
Focuses on topology and relative spacing, not absolute pixels.
"""
from typing import List, Dict, Any
from pydantic import BaseModel
import hashlib

from app.services.geometry_adapter.models import SpatialRegionEvidence

class GridDensity(BaseModel):
    resolution: int = 10
    cells: Dict[str, int]  # "x_y" -> count

class TemplateFingerprint(BaseModel):
    template_id: str
    grid_density: GridDensity
    region_count: int
    aspect_ratio: float
    # Future: line_graph_structure, spacing_matrix, etc.

def build_fingerprint(template_id: str, regions: List[SpatialRegionEvidence], page_w: int, page_h: int) -> TemplateFingerprint:
    """
    Builds a structural fingerprint based on region density across a normalized grid.
    This provides resilience against translation and minor scaling.
    """
    resolution = 10
    cells = {}
    
    # Grid sizes
    cw = page_w / resolution
    ch = page_h / resolution
    
    for r in regions:
        # Find which grid cell the center of the region falls into
        cx = (r.bbox.x1 + r.bbox.x2) / 2
        cy = (r.bbox.y1 + r.bbox.y2) / 2
        
        gx = min(int(cx / cw), resolution - 1)
        gy = min(int(cy / ch), resolution - 1)
        
        key = f"{gx}_{gy}"
        cells[key] = cells.get(key, 0) + 1
        
    aspect_ratio = page_w / page_h if page_h > 0 else 1.0
    
    return TemplateFingerprint(
        template_id=template_id,
        grid_density=GridDensity(resolution=resolution, cells=cells),
        region_count=len(regions),
        aspect_ratio=aspect_ratio
    )
