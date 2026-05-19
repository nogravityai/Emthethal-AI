import logging
from typing import List
from app.services.spatial.models import AssignmentEvidence
from app.services.fusion.models import LayoutHypothesis
from app.models.schemas import BoundingBox

logger = logging.getLogger(__name__)

class AssignmentConsistencyError(Exception):
    """Raised when spatial assignment breaks core geometric axioms."""
    pass

def validate_assignment_consistency(
    assignments: List[AssignmentEvidence],
    regions: List[LayoutHypothesis],
    anchors: List[BoundingBox]
) -> bool:
    """
    Sanity firewall (TASK-P3-02E).
    Must pass before any evidence is handed over to the Fusion Engine.
    """
    
    # 1. Orphan Explosion Check
    orphan_count = sum(1 for a in assignments if a.orphaned)
    if len(assignments) > 0 and (orphan_count / len(assignments)) > 0.4:
        logger.error("VALIDATION FAILED: Orphan explosion detected (>40% of tokens). Assignment engine failure.")
        raise AssignmentConsistencyError("Orphan explosion threshold exceeded.")
        
    # 2. Impossible Region Check
    valid_region_ids = {r.hypothesis_id for r in regions}
    for a in assignments:
        if not a.orphaned and a.region_id not in valid_region_ids:
            logger.error(f"VALIDATION FAILED: Token assigned to non-existent region {a.region_id}.")
            raise AssignmentConsistencyError(f"Invalid region reference: {a.region_id}")

    # 3. Duplicate Conflict Assignments
    # Ensure a single token is not assigned twice in conflicting ways 
    # (unless specifically resolved into a shared cell structure, which is handled later).
    seen_tokens = set()
    for a in assignments:
        if a.orphaned: continue
        for tid in a.token_ids:
            if tid in seen_tokens:
                logger.error(f"VALIDATION FAILED: Token {tid} has multiple conflicting deterministic assignments.")
                raise AssignmentConsistencyError(f"Duplicate assignment for token {tid}.")
            seen_tokens.add(tid)
            
    # If all passed, we are structurally sane.
    logger.info(f"Assignment consistency passed. Orphans: {orphan_count}/{len(assignments)}")
    return True
