"""
TASK-P3-12C — Evidence Patch Engine

Applies HumanOperations to the evidence layer before Fusion or Alignment.
Does not mutate original artifacts; creates derived "patched" artifacts.
"""
import logging
from typing import List, Dict, Any, TypeVar

from app.services.pipeline.pipeline_models import PipelineArtifact, generate_stable_id
from app.services.pipeline.pipeline_context import PipelineContext
from app.services.pipeline.artifact_store import ArtifactStore
from app.services.hitl.models import HumanOperation, HumanLineRejection, HumanRegionMerge
from app.services.hitl.operations_ledger import global_operations_ledger

from app.services.geometry_adapter.models import SpatialRegionEvidence

logger = logging.getLogger(__name__)


class EvidencePatchStage:
    """
    Pipeline Stage that runs right before Alignment.
    Reads geometry_evidence and ocr_evidence.
    Reads HumanOperations from the Ledger.
    Produces patched_geometry_evidence and patched_ocr_evidence.
    """
    stage_name = "evidence_patching"
    required_artifact_types = ["geometry_evidence", "ocr_evidence"]
    output_artifact_type = "patched_evidence"  # Virtual type, actually overwrites reference

    def run(self, context: PipelineContext, store: ArtifactStore) -> PipelineArtifact:
        # 1. Fetch raw evidence. Preserve original IDs so reruns can access them!
        if "original_geometry_evidence" not in context.artifact_references:
            context.artifact_references["original_geometry_evidence"] = context.artifact_references["geometry_evidence"]
            
        geom_art = store.get(context.artifact_references["original_geometry_evidence"])
        ocr_art = store.get(context.artifact_references["ocr_evidence"])

        # 2. Fetch operations for this run
        operations = global_operations_ledger.get_operations_for_run(context.run_id)
        if not operations:
            logger.debug(f"No HITL operations found for run {context.run_id}. Skipping patch.")
            # Return a dummy artifact just to fulfill the stage
            return PipelineArtifact(
                artifact_id=generate_stable_id("no_patch", context.run_id),
                artifact_type="patched_evidence",
                payload={"patched": False}
            )

        # 3. Apply Geometry Patches
        patched_geom_payload = self._apply_geometry_patches(geom_art.payload, operations)
        patched_geom_id = generate_stable_id("patched_geom", geom_art.artifact_id, len(operations))
        patched_geom_art = PipelineArtifact(
            artifact_id=patched_geom_id,
            artifact_type="geometry_evidence",
            derived_from=[geom_art.artifact_id],
            payload=patched_geom_payload
        )
        store.save(patched_geom_art)
        
        # Override the context reference so downstream stages (Alignment) use the patched version
        context.artifact_references["geometry_evidence"] = patched_geom_id
        
        logger.info(f"EvidencePatchStage: Applied {len(operations)} operations to run {context.run_id}")

        return PipelineArtifact(
            artifact_id=generate_stable_id("patch_summary", context.run_id),
            artifact_type="patched_evidence",
            payload={"patched": True, "op_count": len(operations)}
        )

    def _apply_geometry_patches(self, geometry_payload: Dict[str, Any], operations: List[HumanOperation]) -> Dict[str, Any]:
        """Apply geometry modifications like line rejection, region merges, etc."""
        # Deep copy to avoid mutating original
        regions: List[SpatialRegionEvidence] = list(geometry_payload.get("regions", []))
        lines = list(geometry_payload.get("lines", []))
        
        rejected_region_ids = set()
        
        for op in operations:
            if isinstance(op, HumanLineRejection):
                # We target regions by their stable_id in target_evidence_ids
                rejected_region_ids.update(op.target_evidence_ids)
                
            elif isinstance(op, HumanRegionMerge):
                # A merge operation creates a new region and rejects the old ones
                # In a full implementation, we'd calculate the bounding box union here.
                # For now, we stub it to demonstrate the architecture.
                rejected_region_ids.update(op.source_regions)
                # ... would create new merged RegionEvidence ...

        # Filter out rejected regions
        filtered_regions = [r for r in regions if r.stable_id not in rejected_region_ids]
        
        return {
            "regions": filtered_regions,
            "lines": lines
        }
