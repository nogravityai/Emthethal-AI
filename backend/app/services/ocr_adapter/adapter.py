from typing import List, Dict, Any
import logging

import re
from app.models.schemas import BoundingBox, CoordinateSpace
from app.services.ocr_adapter.models import OCRTokenEvidence, CoordinateTransformTrace
from app.services.pipeline.pipeline_models import PipelineArtifact, generate_stable_id
from app.services.pipeline.pipeline_context import PipelineContext
from app.services.pipeline.artifact_store import ArtifactStore
from app.services.pipeline.stage_runner import PipelineStage

logger = logging.getLogger(__name__)

def sanitize_ocr_text(text: str) -> str:
    """
    Sanitize raw OCR/extracted text to remove tofu squares, non-renderable characters,
    meaningless dotted lines/form placeholders, and bracketed empty spaces,
    while preserving PUA characters crucial for Arabic fonts in protected PDFs.
    
    Uses an explicit non-semantic character class to filter out isolated layout
    punctuation, brackets, colons, and parentheses while perfectly keeping PUA Arabic words.
    """
    if not text:
        return ""
        
    # 1. Remove standard control characters
    text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)
    
    # 2. If the text consists entirely of dots, underscores, dashes, spaces, brackets, squares, colons, 
    # or custom dot leaders (like \uf02e, \uf02d, \uf022), clear it.
    if re.match(r'^[._\-\s▢\u25a0-\u25ff\ufffd\[\]\(\):/\\|{}+=*?;!,\u061b\u060C\uf02e\uf02d\uf022]+$', text):
        return ""
        
    # 3. If it is a repeated pattern of a single character (like dotted lines \uf02e\uf02e\uf02e), clear it
    cleaned_no_spaces = text.replace(" ", "")
    if len(cleaned_no_spaces) >= 3 and len(set(cleaned_no_spaces)) <= 1:
        return ""
        
    # 4. Remove leading/trailing repeated PUA/custom symbols (e.g. \uf02e\uf02e\uf02e)
    # Matches any character repeated 3 or more times at the start or end of string
    text = re.sub(r'^\s*((.)\2{2,})', '', text)
    text = re.sub(r'((.)\2{2,})\s*$', '', text)
    
    # 5. Remove leading/trailing standard placeholder characters, tofu squares, brackets, and colons
    text = re.sub(r'^[._\-\s▢\u25a0-\u25ff\ufffd\[\]\(\):/\\|{}+=*?;!,\u061b\u060C\uf02e\uf02d\uf022]+|[._\-\s▢\u25a0-\u25ff\ufffd\[\]\(\):/\\|{}+=*?;!,\u061b\u060C\uf02e\uf02d\uf022]+$', '', text)
    
    return text.strip()

def normalize_ocr_output(raw_tokens: List[Dict[str, Any]], page_width: int, page_height: int, source_engine: str, page_number: int, engine_version: str = "unknown") -> List[OCRTokenEvidence]:
    """
    Dumb adapter: Maps raw dictionaries into strictly governed OCRTokenEvidence.
    Enforces Coordinate Governance (forces PAGE_PIXELS).
    NO text merging, NO heuristics, NO geometry repair allowed here.
    """
    evidence_list = []
    
    for rt in raw_tokens:
        text = rt.get("text", "")
        sanitized_text = sanitize_ocr_text(text)
        if not sanitized_text:
            # Skip empty or meaningless placeholder dotted lines/tofu squares
            continue
            
        # 1. Extract raw coordinates
        # Assume incoming is [x1, y1, x2, y2]
        x1, y1, x2, y2 = rt.get("bbox", [0, 0, 0, 0])
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
            text=sanitized_text,
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
