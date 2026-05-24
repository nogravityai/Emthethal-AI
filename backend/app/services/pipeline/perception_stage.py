"""
services/pipeline/perception_stage.py — Emthethal AI
===================================================
Implementation of the 3-layer Governance Model: Perception Stage.
Coalesces OCR, Geometry, Coordinate Space, and Primitive Shape engines.
"""

import logging
from typing import List, Dict, Any
from app.services.pipeline.pipeline_models import PipelineArtifact, generate_stable_id
from app.services.pipeline.pipeline_context import PipelineContext
from app.services.pipeline.artifact_store import ArtifactStore
from app.services.pipeline.stage_runner import PipelineStage

from app.services.ocr_adapter.adapter import normalize_ocr_output
from app.services.geometry_adapter.adapter import normalize_geometry_output
from app.core.charts.models import ShapeEmbedding

logger = logging.getLogger(__name__)


class OCRAdapterEngine:
    """
    Ingests raw OCR dictionaries and transforms them into normalized OCRTokenEvidence.
    """
    def run(self, raw_ocr_dicts_art: PipelineArtifact) -> PipelineArtifact:
        payload = raw_ocr_dicts_art.payload
        raw_tokens = payload.get("tokens", [])
        page_w = payload.get("page_width", 1000)
        page_h = payload.get("page_height", 1000)
        source = payload.get("source_engine", "unknown")
        engine_v = payload.get("engine_version", "unknown")
        page_num = payload.get("page_number", 1)

        evidence_list = normalize_ocr_output(raw_tokens, page_w, page_h, source, page_num, engine_v)
        art_id = generate_stable_id("ocr_evidence", raw_ocr_dicts_art.artifact_id, len(evidence_list))

        return PipelineArtifact(
            artifact_id=art_id,
            artifact_type="ocr_evidence",
            derived_from=[raw_ocr_dicts_art.artifact_id],
            payload=evidence_list
        )


class GeometryAdapterEngine:
    """
    Ingests raw CV2 geometry dictionaries and maps them into DetectedBoxEvidence,
    DetectedLineEvidence, and SpatialRegionEvidence.
    """
    def run(self, raw_cv2_dicts_art: PipelineArtifact) -> PipelineArtifact:
        normalized = normalize_geometry_output(raw_cv2_dicts_art.payload)
        art_id = generate_stable_id("geom_evidence", raw_cv2_dicts_art.artifact_id)

        return PipelineArtifact(
            artifact_id=art_id,
            artifact_type="geometry_evidence",
            derived_from=[raw_cv2_dicts_art.artifact_id],
            payload=normalized
        )


class CoordinateSpaceDetectorEngine:
    """
    Detects layout dimensions and assumed coordinate spaces / scales/ DPI.
    """
    def run(self, raw_ocr_dicts_art: PipelineArtifact, raw_cv2_dicts_art: PipelineArtifact) -> PipelineArtifact:
        ocr_payload = raw_ocr_dicts_art.payload
        geom_payload = raw_cv2_dicts_art.payload

        page_w = ocr_payload.get("page_width", geom_payload.get("meta", {}).get("page_width", 1000))
        page_h = ocr_payload.get("page_height", geom_payload.get("meta", {}).get("page_height", 1000))

        detected_space = {
            "page_width": page_w,
            "page_height": page_h,
            "coordinate_space": "page_pixels",
            "detected_dpi": ocr_payload.get("detected_dpi", 200)
        }

        art_id = generate_stable_id(
            "coordinate_space_evidence",
            raw_ocr_dicts_art.artifact_id,
            raw_cv2_dicts_art.artifact_id
        )
        return PipelineArtifact(
            artifact_id=art_id,
            artifact_type="coordinate_space_evidence",
            derived_from=[raw_ocr_dicts_art.artifact_id, raw_cv2_dicts_art.artifact_id],
            payload=detected_space
        )


class PrimitiveShapeEngine:
    """
    Extracts primitive contours and shape embeddings (including invariant Hu moments).
    """
    def run(self, geometry_evidence_art: PipelineArtifact) -> PipelineArtifact:
        boxes = geometry_evidence_art.payload.get("boxes", [])
        shapes: List[ShapeEmbedding] = []

        for box in boxes:
            bbox = box.bbox
            w = bbox.width
            h = bbox.height
            if w <= 0 or h <= 0:
                continue

            # Calculate analytical scale/rotation invariant Hu moments for rectangles
            eta_20 = w / (12.0 * h) if h != 0 else 0.0
            eta_02 = h / (12.0 * w) if w != 0 else 0.0
            h1 = eta_20 + eta_02
            h2 = (eta_20 - eta_02) ** 2

            # Analytical Hu moments for a symmetric bounding box (other moments are zero due to symmetry)
            hu_moments = [h1, h2, 0.0, 0.0, 0.0, 0.0, 0.0]

            shapes.append(
                ShapeEmbedding(
                    hu_moments=hu_moments,
                    area=bbox.area,
                    perimeter=2.0 * (w + h),
                    aspect_ratio=w / h if h != 0 else 0.0,
                    centroid=bbox.center
                )
            )

        art_id = generate_stable_id("shape_evidence", geometry_evidence_art.artifact_id, len(shapes))
        return PipelineArtifact(
            artifact_id=art_id,
            artifact_type="shape_evidence",
            derived_from=[geometry_evidence_art.artifact_id],
            payload=shapes
        )


class PerceptionStage:
    """
    Unified Pipeline Stage for the entire Perception layer.
    Coordinates all perception engines sequentially.
    """
    stage_name = "perception"
    required_artifact_types = ["raw_ocr_dicts", "raw_cv2_dicts"]
    output_artifact_type = "perception_data"

    def run(self, context: PipelineContext, store: ArtifactStore) -> PipelineArtifact:
        raw_ocr = store.get(context.artifact_references["raw_ocr_dicts"])
        raw_cv2 = store.get(context.artifact_references["raw_cv2_dicts"])

        # 1. Execute OCRAdapterEngine
        ocr_art = OCRAdapterEngine().run(raw_ocr)
        store.save(ocr_art)
        context.register_artifact("ocr_evidence", ocr_art.artifact_id)

        # 2. Execute GeometryAdapterEngine
        geom_art = GeometryAdapterEngine().run(raw_cv2)
        store.save(geom_art)
        context.register_artifact("geometry_evidence", geom_art.artifact_id)

        # 3. Execute CoordinateSpaceDetectorEngine
        coords_art = CoordinateSpaceDetectorEngine().run(raw_ocr, raw_cv2)
        store.save(coords_art)
        context.register_artifact("coordinate_space_evidence", coords_art.artifact_id)

        # 4. Execute PrimitiveShapeEngine
        shapes_art = PrimitiveShapeEngine().run(geom_art)
        store.save(shapes_art)
        context.register_artifact("shape_evidence", shapes_art.artifact_id)

        # Build final perception summary artifact
        art_id = generate_stable_id("perception_stage_summary", context.run_id)
        return PipelineArtifact(
            artifact_id=art_id,
            artifact_type="perception_data",
            derived_from=[raw_ocr.artifact_id, raw_cv2.artifact_id],
            payload={
                "ocr_tokens_count": len(ocr_art.payload),
                "geometry_boxes_count": len(geom_art.payload.get("boxes", [])),
                "geometry_lines_count": len(geom_art.payload.get("lines", [])),
                "shapes_count": len(shapes_art.payload),
                "coordinate_space": coords_art.payload["coordinate_space"]
            }
        )
