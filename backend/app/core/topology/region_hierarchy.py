import logging
from typing import List, Dict, Any, Optional
from app.models.schemas import BoundingBox, RegionHierarchyEvidence, CoordinateSpace
from app.services.pipeline.pipeline_models import generate_stable_id

logger = logging.getLogger(__name__)

class RegionHierarchyInference:
    """
    Builds a hierarchical document structure tree:
    page -> section -> table -> row -> cell.
    Uses spatial containment (smallest containing bounding box).
    """
    def infer_hierarchy(
        self,
        page_number: int,
        page_width: int,
        page_height: int,
        table_topologies: List[Any],
        flat_regions: List[Any]
    ) -> List[RegionHierarchyEvidence]:
        # 1. Create page-level box
        page_bbox = BoundingBox(
            x1=0.0, y1=0.0, x2=float(page_width), y2=float(page_height),
            coordinate_space=CoordinateSpace.PAGE_PIXELS,
            page_width=page_width, page_height=page_height
        )
        page_id = f"page_{page_number}"
        
        hierarchy = []
        nodes: Dict[str, Dict[str, Any]] = {}
        
        # Add page node
        nodes[page_id] = {
            "element_id": page_id,
            "element_type": "page",
            "bbox": page_bbox,
            "parent_id": None,
            "children_ids": []
        }

        # 2. Group topologies by table
        tables_map = {}
        for topo in table_topologies:
            t_id = topo.table_id
            if t_id not in tables_map:
                tables_map[t_id] = []
            tables_map[t_id].append(topo)

        # Create Table and Row nodes
        for t_id, topos in tables_map.items():
            tx1 = min(t.bbox.x1 for t in topos)
            ty1 = min(t.bbox.y1 for t in topos)
            tx2 = max(t.bbox.x2 for t in topos)
            ty2 = max(t.bbox.y2 for t in topos)
            t_bbox = BoundingBox(
                x1=tx1, y1=ty1, x2=tx2, y2=ty2,
                coordinate_space=CoordinateSpace.PAGE_PIXELS,
                page_width=page_width, page_height=page_height
            )
            
            nodes[t_id] = {
                "element_id": t_id,
                "element_type": "table",
                "bbox": t_bbox,
                "parent_id": page_id,
                "children_ids": []
            }
            
            rows_map = {}
            for topo in topos:
                r_idx = topo.row_index
                r_id = f"{t_id}_row_{r_idx}"
                if r_id not in rows_map:
                    rows_map[r_id] = []
                rows_map[r_id].append(topo)
                
            for r_id, row_topos in rows_map.items():
                rx1 = min(t.bbox.x1 for t in row_topos)
                ry1 = min(t.bbox.y1 for t in row_topos)
                rx2 = max(t.bbox.x2 for t in row_topos)
                ry2 = max(t.bbox.y2 for t in row_topos)
                r_bbox = BoundingBox(
                    x1=rx1, y1=ry1, x2=rx2, y2=ry2,
                    coordinate_space=CoordinateSpace.PAGE_PIXELS,
                    page_width=page_width, page_height=page_height
                )
                
                nodes[r_id] = {
                    "element_id": r_id,
                    "element_type": "row",
                    "bbox": r_bbox,
                    "parent_id": t_id,
                    "children_ids": []
                }
                nodes[t_id]["children_ids"].append(r_id)
                
                for topo in row_topos:
                    c_id = topo.cell_id
                    nodes[c_id] = {
                        "element_id": c_id,
                        "element_type": "cell",
                        "bbox": topo.bbox,
                        "parent_id": r_id,
                        "children_ids": []
                    }
                    nodes[r_id]["children_ids"].append(c_id)

        # 3. Add flat sections (large regions that are not tables)
        for reg in flat_regions:
            reg_id = getattr(reg, "stable_id", None)
            if reg_id in nodes:
                continue
            
            is_large = reg.bbox.width > page_width * 0.4 and reg.bbox.height > page_height * 0.1
            element_type = "section" if is_large else "cell"
            
            nodes[reg_id] = {
                "element_id": reg_id,
                "element_type": element_type,
                "bbox": reg.bbox,
                "parent_id": page_id,
                "children_ids": []
            }

        # 4. Resolve spatial containment (build hierarchical parent links)
        for n_id, node in list(nodes.items()):
            if n_id == page_id:
                continue
            
            element_type = node["element_type"]
            if element_type in ("row", "cell") and node["parent_id"] != page_id:
                continue
                
            best_parent_id = page_id
            best_parent_area = page_bbox.area
            
            for other_id, other in nodes.items():
                if other_id == n_id or other_id == page_id:
                    continue
                if other["element_type"] not in ("section", "table"):
                    continue
                
                if self._is_contained(node["bbox"], other["bbox"]):
                    other_area = other["bbox"].area
                    if other_area < best_parent_area:
                        best_parent_id = other_id
                        best_parent_area = other_area
                        
            node["parent_id"] = best_parent_id

        # Clear default kids and build clean parent-child hierarchy
        for n_id, node in nodes.items():
            if n_id != page_id and node["element_type"] not in ("row", "cell"):
                node["children_ids"] = []
        
        # Build children relations
        for n_id, node in nodes.items():
            p_id = node["parent_id"]
            if p_id and p_id in nodes:
                if n_id not in nodes[p_id]["children_ids"]:
                    nodes[p_id]["children_ids"].append(n_id)

        for n_id, node in nodes.items():
            stable_id = generate_stable_id("hierarchy", page_number, n_id, node["parent_id"] or "none")
            hierarchy.append(RegionHierarchyEvidence(
                stable_id=stable_id,
                page_number=page_number,
                element_id=node["element_id"],
                element_type=node["element_type"],
                parent_id=node["parent_id"],
                children_ids=node["children_ids"],
                bbox=node["bbox"],
                coordinate_space=CoordinateSpace.PAGE_PIXELS
            ))
            
        return hierarchy

    def _is_contained(self, inner: BoundingBox, outer: BoundingBox) -> bool:
        """True if inner box is structurally contained inside outer box."""
        ix1 = max(inner.x1, outer.x1)
        iy1 = max(inner.y1, outer.y1)
        ix2 = min(inner.x2, outer.x2)
        iy2 = min(inner.y2, outer.y2)
        
        if ix2 <= ix1 or iy2 <= iy1:
            return False
            
        inter_area = (ix2 - ix1) * (iy2 - iy1)
        containment = inter_area / inner.area
        return containment > 0.85
