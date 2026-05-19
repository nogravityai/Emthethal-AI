from typing import List, Tuple, Any
import logging

from app.models.schemas import BoundingBox, CoordinateSpace
from app.services.alignment.models import AlignmentEvidence, AlignmentType, OverlapMetrics
from app.services.pipeline.pipeline_models import PipelineArtifact, generate_stable_id
from app.services.pipeline.pipeline_context import PipelineContext
from app.services.pipeline.artifact_store import ArtifactStore

logger = logging.getLogger(__name__)

TOUCHING_THRESHOLD = 20.0  # px — within this margin = touching, not inside


def validate_coordinate_alignment(token_bbox: BoundingBox, region_bbox: BoundingBox) -> List[str]:
    """
    Explicit coordinate space firewall.
    Rejects silently drifted bbox coordinates before alignment.
    """
    violations = []
    if token_bbox.coordinate_space != CoordinateSpace.PAGE_PIXELS:
        violations.append(f"Token bbox is in '{token_bbox.coordinate_space}', expected PAGE_PIXELS")
    if region_bbox.coordinate_space != CoordinateSpace.PAGE_PIXELS:
        violations.append(f"Region bbox is in '{region_bbox.coordinate_space}', expected PAGE_PIXELS")
    if token_bbox.page_width != region_bbox.page_width or token_bbox.page_height != region_bbox.page_height:
        violations.append(f"Page dimensions mismatch: token ({token_bbox.page_width}x{token_bbox.page_height}) vs region ({region_bbox.page_width}x{region_bbox.page_height})")
    return violations


def _compute_overlap_metrics(t: BoundingBox, r: BoundingBox) -> OverlapMetrics:
    """Deterministic intersection geometry — no randomness."""
    ix1 = max(t.x1, r.x1)
    iy1 = max(t.y1, r.y1)
    ix2 = min(t.x2, r.x2)
    iy2 = min(t.y2, r.y2)

    inter_area = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    t_area = max(0.0, (t.x2 - t.x1) * (t.y2 - t.y1))
    r_area = max(0.0, (r.x2 - r.x1) * (r.y2 - r.y1))
    union_area = t_area + r_area - inter_area

    iou = inter_area / union_area if union_area > 0 else 0.0
    token_cov = inter_area / t_area if t_area > 0 else 0.0
    region_cov = inter_area / r_area if r_area > 0 else 0.0

    t_cx = (t.x1 + t.x2) / 2
    t_cy = (t.y1 + t.y2) / 2
    r_cx = (r.x1 + r.x2) / 2
    r_cy = (r.y1 + r.y2) / 2
    dist = ((t_cx - r_cx) ** 2 + (t_cy - r_cy) ** 2) ** 0.5

    return OverlapMetrics(
        iou=round(iou, 4),
        intersection_area=round(inter_area, 2),
        token_coverage=round(token_cov, 4),
        region_coverage=round(region_cov, 4),
        centroid_distance=round(dist, 2),
    )


def _classify_alignment(metrics: OverlapMetrics, t: BoundingBox, r: BoundingBox) -> Tuple[AlignmentType, float]:
    """
    Pure classification — no heuristics. Three states only.
    Engine NEVER decides ambiguity; it surfaces it as separate evidence.
    """
    if metrics.token_coverage >= 0.85:
        return AlignmentType.TOKEN_INSIDE_REGION, metrics.token_coverage

    if metrics.intersection_area > 0:
        return AlignmentType.TOKEN_CROSSES_BOUNDARY, metrics.iou

    # Check touching (expand region by threshold)
    expanded = BoundingBox(
        x1=r.x1 - TOUCHING_THRESHOLD, y1=r.y1 - TOUCHING_THRESHOLD,
        x2=r.x2 + TOUCHING_THRESHOLD, y2=r.y2 + TOUCHING_THRESHOLD,
        coordinate_space=r.coordinate_space,
        page_width=r.page_width, page_height=r.page_height
    )
    touch_metrics = _compute_overlap_metrics(t, expanded)
    if touch_metrics.intersection_area > 0:
        score = max(0.1, 1.0 - (metrics.centroid_distance / 100.0))
        return AlignmentType.TOKEN_TOUCHING_REGION, round(score, 4)

    return None, 0.0


def align_tokens_to_regions(
    ocr_evidence: List[Any],
    spatial_regions: List[Any],
) -> List[AlignmentEvidence]:
    """
    Core alignment loop. 
    For EVERY token-region pair, emit AlignmentEvidence if a relationship exists.
    Ambiguity = multiple evidence items. Fusion decides later.
    """
    alignments = []

    for token in ocr_evidence:
        token_id = getattr(token, "stable_id", getattr(token, "token_id", None))
        t_bbox = token.bbox
        found_any = False

        for region in spatial_regions:
            region_id = getattr(region, "stable_id", getattr(region, "hypothesis_id", None))
            r_bbox = region.bbox

            # Coordinate Firewall
            violations = validate_coordinate_alignment(t_bbox, r_bbox)
            if violations:
                logger.error(f"COORDINATE DRIFT: {violations}")
                alignments.append(AlignmentEvidence.create(
                    source_id=token_id, target_id=region_id,
                    alignment_type=AlignmentType.TOKEN_CROSSES_BOUNDARY,
                    score=0.0,
                    metrics=OverlapMetrics(),
                    rejection_reasons=violations
                ))
                continue

            metrics = _compute_overlap_metrics(t_bbox, r_bbox)
            a_type, score = _classify_alignment(metrics, t_bbox, r_bbox)

            if a_type is not None:
                ev = AlignmentEvidence.create(
                    source_id=token_id,
                    target_id=region_id,
                    alignment_type=a_type,
                    score=score,
                    metrics=metrics
                )
                alignments.append(ev)
                found_any = True
                logger.debug(f"ALIGNED: {token_id[:8]}.. → {region_id[:8] if len(region_id) > 8 else region_id} [{a_type.value}] score={score}")

        if not found_any:
            logger.debug(f"ORPHAN TOKEN (no alignment): {token_id}")

    return alignments


class AlignmentStage:
    stage_name = "alignment"
    required_artifact_types = ["ocr_evidence", "geometry_evidence"]
    output_artifact_type = "alignment_evidence"

    def run(self, context: PipelineContext, store: ArtifactStore) -> PipelineArtifact:
        ocr_art = store.get(context.artifact_references["ocr_evidence"])
        geom_art = store.get(context.artifact_references["geometry_evidence"])

        regions = geom_art.payload["regions"]
        alignments = align_tokens_to_regions(ocr_art.payload, regions)

        art_id = generate_stable_id("alignment", ocr_art.artifact_id, geom_art.artifact_id)
        return PipelineArtifact(
            artifact_id=art_id,
            artifact_type="alignment_evidence",
            derived_from=[ocr_art.artifact_id, geom_art.artifact_id],
            payload=alignments
        )
