import cv2
import numpy as np
from app.services.debug.debug_snapshot import AssignmentDebugSnapshot
from app.services.debug.color_legend import DebugSemanticColor

def draw_assignment_overlay(page_image: np.ndarray, snapshot: AssignmentDebugSnapshot) -> np.ndarray:
    """
    Renders the AssignmentDebugSnapshot onto a given page image.
    Crucially, this uses ONLY the serialized snapshot, decoupling rendering from the AssignmentEngine.
    """
    img = page_image.copy()
    
    # Draw Regions
    for r in snapshot.regions:
        x1, y1, x2, y2 = map(int, [r.bbox.x1, r.bbox.y1, r.bbox.x2, r.bbox.y2])
        cv2.rectangle(img, (x1, y1), (x2, y2), DebugSemanticColor.REGION.value, 1)
        
    # Draw Anchors (Forbidden Crossings)
    for a in snapshot.anchors:
        x1, y1, x2, y2 = map(int, [a.bbox.x1, a.bbox.y1, a.bbox.x2, a.bbox.y2])
        cv2.rectangle(img, (x1, y1), (x2, y2), DebugSemanticColor.ANCHOR.value, 2)
        
    # Draw Accepted Assignments (Arrows token -> region)
    region_map = {r.region_id: r for r in snapshot.regions}
    token_map = {t.token_id: t for t in snapshot.tokens}
    
    for assign in snapshot.assignments:
        region = region_map.get(assign.region_id)
        if not region: continue
        
        rx = int((region.bbox.x1 + region.bbox.x2) / 2)
        ry = int((region.bbox.y1 + region.bbox.y2) / 2)
        
        for tid in assign.token_ids:
            token = token_map.get(tid)
            if not token: continue
            
            tx = int((token.bbox.x1 + token.bbox.x2) / 2)
            ty = int((token.bbox.y1 + token.bbox.y2) / 2)
            
            color = DebugSemanticColor.ACCEPTED.value
            if assign.is_orphan_recovered:
                color = DebugSemanticColor.WARNING.value  # Yellow for recovered
                
            cv2.arrowedLine(img, (tx, ty), (rx, ry), color, 1, tipLength=0.1)
            cv2.putText(img, f"{assign.score:.2f}", (tx, ty - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.3, color, 1)

    # Draw Orphans
    for orphan in snapshot.orphan_tokens:
        x1, y1, x2, y2 = map(int, [orphan.bbox.x1, orphan.bbox.y1, orphan.bbox.x2, orphan.bbox.y2])
        cv2.rectangle(img, (x1, y1), (x2, y2), DebugSemanticColor.ORPHAN.value, 2)
        
    # Draw Rejected Assignments (Red cross or dotted line)
    for reject in snapshot.rejected_assignments:
        region = region_map.get(reject.region_id)
        if not region: continue
        rx = int((region.bbox.x1 + region.bbox.x2) / 2)
        ry = int((region.bbox.y1 + region.bbox.y2) / 2)
        
        for tid in reject.token_ids:
            token = token_map.get(tid)
            if not token: continue
            
            tx = int((token.bbox.x1 + token.bbox.x2) / 2)
            ty = int((token.bbox.y1 + token.bbox.y2) / 2)
            
            cv2.line(img, (tx, ty), (rx, ry), DebugSemanticColor.REJECTED.value, 1, cv2.LINE_4)
            cv2.putText(img, "REJECTED", (tx, ty + 10), cv2.FONT_HERSHEY_SIMPLEX, 0.3, DebugSemanticColor.REJECTED.value, 1)

    return img
