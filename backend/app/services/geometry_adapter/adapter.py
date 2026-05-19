from typing import List, Dict, Any
import logging

from app.models.schemas import BoundingBox, CoordinateSpace
from app.services.geometry_adapter.models import (
    GeometryProvenance,
    DetectedLineEvidence,
    DetectedBoxEvidence,
    SpatialRegionEvidence
)
from app.services.ocr_adapter.models import CoordinateTransformTrace
from app.services.pipeline.pipeline_models import PipelineArtifact, generate_stable_id
from app.services.pipeline.pipeline_context import PipelineContext
from app.services.pipeline.artifact_store import ArtifactStore
from app.services.pipeline.stage_runner import PipelineStage

logger = logging.getLogger(__name__)

def normalize_geometry_output(raw_geometry: Dict[str, Any]) -> Dict[str, List[Any]]:
    """
    Dumb adapter: Maps OpenCV dicts into strictly governed GeometryEvidence.
    NO heuristics, NO merged cell logic. Explicit visible geometry only.
    """
    lines_raw = raw_geometry.get("lines", [])
    boxes_raw = raw_geometry.get("boxes", [])
    meta = raw_geometry.get("meta", {})
    
    page_w = meta.get("page_width", 1000)
    page_h = meta.get("page_height", 1000)
    
    prov = GeometryProvenance(
        source_module="geometry_adapter",
        evidence_type="raw_geometry",
        created_by_stage="geometry_ingestion",
        created_at_pipeline_step=2,
        opencv_version=meta.get("opencv_version", "4.x"),
        kernel_signature=meta.get("kernel_signature", "unknown"),
        dpi_normalization=meta.get("dpi_normalization", "identity"),
        thresholding_profile=meta.get("thresholding_profile", "default")
    )
    
    trace = CoordinateTransformTrace(
        original_space=meta.get("original_space", "unknown"),
        target_space=CoordinateSpace.PAGE_PIXELS.value
    )
    
    evidence_lines = []
    for l in lines_raw:
        x1, y1, x2, y2 = l["bbox"]
        evidence_lines.append(DetectedLineEvidence.create(
            x1, y1, x2, y2, l.get("orientation", "unknown"), l.get("confidence", 1.0), prov, trace, page_w, page_h
        ))
        
    evidence_boxes = []
    evidence_regions = []
    for b in boxes_raw:
        x1, y1, x2, y2 = b["bbox"]
        box_ev = DetectedBoxEvidence.create(
            x1, y1, x2, y2, b.get("confidence", 1.0), prov, trace, page_w, page_h
        )
        evidence_boxes.append(box_ev)
        
        # Explicit 1:1 Region mapping for Assignment Engine targets
        evidence_regions.append(SpatialRegionEvidence.create_from_box(box_ev))
        
    return {
        "lines": evidence_lines,
        "boxes": evidence_boxes,
        "regions": evidence_regions
    }

class GeometryAdapterStage:
    stage_name = "geometry_adapter"
    required_artifact_types = ["raw_cv2_dicts"]
    output_artifact_type = "geometry_evidence"
    
    def run(self, context: PipelineContext, store: ArtifactStore) -> PipelineArtifact:
        raw_art = store.get(context.artifact_references["raw_cv2_dicts"])
        
        normalized = normalize_geometry_output(raw_art.payload)
        
        art_id = generate_stable_id("geom_evidence", raw_art.artifact_id)
        
        return PipelineArtifact(
            artifact_id=art_id,
            artifact_type="geometry_evidence",
            derived_from=[raw_art.artifact_id],
            payload=normalized
        )
