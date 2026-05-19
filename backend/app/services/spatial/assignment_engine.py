import logging
from typing import List, Dict, Any, Optional

from app.models.schemas import BoundingBox
from app.services.fusion.models import LayoutHypothesis, EvidenceProvenance
from app.services.spatial.models import AssignmentEvidence
from app.services.spatial.region_index import SpatialRegionIndex
from app.services.spatial.overlap import compute_overlap_ratio, compute_iou
from app.services.spatial.orphan_recovery import OrphanRecoveryPipeline
from app.services.spatial.token_normalization import normalize_token_fragments

logger = logging.getLogger(__name__)

def crosses_anchor(token_box: BoundingBox, region_box: BoundingBox, anchors: List[BoundingBox]) -> bool:
    """
    Detect if assigning the token to the region crosses a forbidden anchor (like a vertical line or separator).
    """
    for anchor in anchors:
        # Check if the anchor acts as a wall between token center and region center
        tx, ty = (token_box.x1 + token_box.x2) / 2, (token_box.y1 + token_box.y2) / 2
        rx, ry = (region_box.x1 + region_box.x2) / 2, (region_box.y1 + region_box.y2) / 2
        
        # Simple heuristic: if anchor is vertical and strictly between the x-coordinates
        if anchor.x2 - anchor.x1 < 10:  # vertical line
            if min(tx, rx) < anchor.x1 < max(tx, rx):
                # Also ensure they overlap in Y so it's a real wall
                if max(token_box.y1, region_box.y1) < min(token_box.y2, region_box.y2):
                    return True
    return False

def generate_assignment_candidates(token: Any, index: SpatialRegionIndex) -> List[LayoutHypothesis]:
    """Broad-phase: return all regions that MIGHT contain this token using the spatial index."""
    return index.query(token.bbox)

def score_assignment_candidates(
    token: Any, 
    candidates: List[LayoutHypothesis], 
    anchors: List[BoundingBox]
) -> List[AssignmentEvidence]:
    """Narrow-phase: Probabilistic, multi-evidence scoring of all candidates."""
    scored_evidences = []
    
    for region in candidates:
        # Check forbidden crossings first
        if crosses_anchor(token.bbox, region.bbox, anchors):
            logger.debug(f"ANCHOR_VIOLATION: Token {token.text} cannot cross anchor to reach region {region.hypothesis_id}")
            continue
            
        overlap_ratio = compute_overlap_ratio(token.bbox, region.bbox)
        iou_val = compute_iou(token.bbox, region.bbox)
        
        # Simple multi-evidence score
        score = overlap_ratio * 0.7 + iou_val * 0.3
        
        prov = EvidenceProvenance(
            source_module="assignment_engine",
            evidence_type="spatial_overlap",
            confidence_contribution=score,
            reference_ids=[region.hypothesis_id]
        )
        
        evidence = AssignmentEvidence(
            token_ids=[getattr(token, "token_id", "unknown")],
            region_id=region.hypothesis_id,
            page_number=region.page_number,
            assignment_score=score,
            overlap_ratio=overlap_ratio,
            iou_score=iou_val,
            provenance=prov
        )
        scored_evidences.append(evidence)
        
    return scored_evidences

def resolve_assignment(token: Any, scored: List[AssignmentEvidence]) -> AssignmentEvidence:
    """Determine the final assignment from ranked candidates, enforcing capacity/reading order heuristics."""
    if not scored:
        logger.debug(f"ORPHAN_CREATED: Token {token.text} has no valid candidates.")
        # Return an orphaned evidence
        return AssignmentEvidence(
            token_ids=[getattr(token, "token_id", "unknown")],
            region_id=None,
            page_number=token.bbox.page_height, # fallback
            orphaned=True,
            provenance=EvidenceProvenance(source_module="assignment_engine", evidence_type="orphan_creation")
        )
        
    # Rank by assignment score
    ranked = sorted(scored, key=lambda e: e.assignment_score, reverse=True)
    best = ranked[0]
    
    if best.assignment_score < 0.2:
        logger.debug(f"ORPHAN_CREATED: Token {token.text} best score {best.assignment_score} too low.")
        best.orphaned = True
        return best
        
    logger.debug(f"ASSIGNMENT_ACCEPTED: Token {token.text} -> Region {best.region_id} (Score: {best.assignment_score:.2f})")
    return best

def assign_tokens_to_regions(
    tokens: List[Any], 
    regions: List[LayoutHypothesis], 
    anchors: List[BoundingBox],
    page_width: int,
    page_height: int
) -> List[AssignmentEvidence]:
    """
    Main entrypoint for TASK-P3-02. 
    Maps tokens to geometric regions deterministically.
    """
    # 1. Normalize fragments
    normalized_tokens = normalize_token_fragments(tokens)
    
    # 2. Build Index
    index = SpatialRegionIndex(page_width=page_width, page_height=page_height)
    index.build(regions)
    
    orphan_pipeline = OrphanRecoveryPipeline(index, anchors)
    all_evidence = []
    
    # 3. Assign
    for token in normalized_tokens:
        candidates = generate_assignment_candidates(token, index)
        scored = score_assignment_candidates(token, candidates, anchors)
        resolution = resolve_assignment(token, scored)
        
        if resolution.orphaned:
            # Attempt recovery
            recovery = orphan_pipeline.recover(token, regions)
            if recovery:
                logger.debug(f"ORPHAN_RECOVERED: Token {token.text} -> Region {recovery.region_id}")
                all_evidence.append(recovery)
            else:
                all_evidence.append(resolution)
        else:
            all_evidence.append(resolution)
            
    return all_evidence
