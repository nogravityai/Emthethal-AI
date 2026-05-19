from typing import List, Dict, Any
import logging

from app.models.schemas import BoundingBox, CoordinateSpace
from app.services.ocr_adapter.models import OCRTokenEvidence, CoordinateTransformTrace
from app.services.pipeline.pipeline_models import PipelineArtifact, generate_stable_id
from app.services.pipeline.pipeline_context import PipelineContext
from app.services.pipeline.artifact_store import ArtifactStore
from app.services.pipeline.stage_runner import PipelineStage

logger = logging.getLogger(__name__)

def normalize_ocr_output(raw_tokens: List[Dict[str, Any]], page_width: int, page_height: int, source_engine: str, page_number: int, engine_version: str = "unknown") -> List[OCRTokenEvidence]:
    """
    Dumb adapter: Maps raw dictionaries into strictly governed OCRTokenEvidence.
    Enforces Coordinate Governance (forces PAGE_PIXELS).
    NO text merging, NO heuristics, NO geometry repair allowed here.
    """
    evidence_list = []
    
    for rt in raw_tokens:
        # 1. Extract raw coordinates
        # Assume incoming is [x1, y1, x2, y2]
        x1, y1, x2, y2 = rt.get("bbox", [0, 0, 0, 0])
        text = rt.get("text", "")
        conf = rt.get("confidence", 0.0)
        orig_space = rt.get("space", "unknown")
        
        # 2. Coordinate Transform (Mocked identity transform for now)
        # In reality, if orig_space == "pdf_points", we apply 72 DPI -> 200 DPI scale
        scale_x, scale_y = 1.0, 1.0 
        
        trace = CoordinateTransformTrace(
            original_space=orig_space,
            target_space=CoordinateSpace.PAGE_PIXELS.value,
            scale_x=scale_x,
            scale_y=scale_y
        )
        
        bbox = BoundingBox(
            x1=x1 * scale_x,
            y1=y1 * scale_y,
            x2=x2 * scale_x,
            y2=y2 * scale_y,
            coordinate_space=CoordinateSpace.PAGE_PIXELS,
            page_width=page_width,
            page_height=page_height
        )
        
        # 3. Create Evidence
        evidence = OCRTokenEvidence.create(
            text=text,
            bbox=bbox,
            confidence=conf,
            source_engine=source_engine,
            engine_version=engine_version,
            page_number=page_number,
            trace=trace
        )
        evidence_list.append(evidence)
        
    return evidence_list

class OCRAdapterStage:
    """
    Pipeline stage for integrating real OCR outputs safely into the Artifact flow.
    """
    stage_name = "ocr_adapter"
    required_artifact_types = ["raw_ocr_dicts"]
    output_artifact_type = "ocr_evidence"
    
    def run(self, context: PipelineContext, store: ArtifactStore) -> PipelineArtifact:
        raw_art = store.get(context.artifact_references["raw_ocr_dicts"])
        
        payload = raw_art.payload
        raw_tokens = payload.get("tokens", [])
        page_w = payload.get("page_width", 1000)
        page_h = payload.get("page_height", 1000)
        source = payload.get("source_engine", "unknown")
        engine_v = payload.get("engine_version", "unknown")
        page_num = payload.get("page_number", 1)
        
        evidence_list = normalize_ocr_output(raw_tokens, page_w, page_h, source, page_num, engine_v)
        
        # We must package it into a deterministic artifact
        art_id = generate_stable_id("ocr_evidence", raw_art.artifact_id, len(evidence_list))
        
        return PipelineArtifact(
            artifact_id=art_id,
            artifact_type="ocr_evidence",
            derived_from=[raw_art.artifact_id],
            payload=evidence_list
        )
