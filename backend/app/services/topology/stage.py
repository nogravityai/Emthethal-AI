import logging
from typing import List, Dict, Any, Optional

from app.services.pipeline.pipeline_models import PipelineArtifact, generate_stable_id
from app.services.pipeline.pipeline_context import PipelineContext
from app.services.pipeline.artifact_store import ArtifactStore
from app.services.pipeline.stage_runner import PipelineStage
from app.models.schemas import BoundingBox, CoordinateSpace, TableTopologyEvidence, RegionHierarchyEvidence

from app.core.topology.table_topology_resolver import TableTopologyResolver
from app.core.topology.region_hierarchy import RegionHierarchyInference
from app.core.topology.checkbox_semantic_linker import CheckboxSemanticLinker
from app.core.topology.arabic_stabilizer import ArabicReadingFlowStabilizer
from app.core.topology.semantic_grid import LogicalCellOwnershipResolver, ArabicTokenComposer

from app.services.topology.models import TopologyEvidencePayload

logger = logging.getLogger(__name__)

class TopologyStage(PipelineStage):
    """
    Topology Reconstruction Pipeline Stage.
    Runs after geometry/ocr adapters & patching.
    Builds:
      - Logical Table Grid topology
      - Parent-child containment hierarchy
      - Semantic checkbox linking (weighted scoring)
      - Stabilized Arabic reading order (RTL tokens sorting)
    """
    stage_name = "topology_reconstruction"
    required_artifact_types = ["geometry_evidence", "ocr_evidence"]
    output_artifact_type = "topology_evidence"

    def run(self, context: PipelineContext, store: ArtifactStore) -> PipelineArtifact:
        logger.info(f"Running TopologyStage for run {context.run_id}")

        geom_art = store.get(context.artifact_references["geometry_evidence"])
        ocr_art = store.get(context.artifact_references["ocr_evidence"])

        # Fetch lines, boxes, and regions from geometry evidence
        lines = geom_art.payload.get("lines", [])
        regions = geom_art.payload.get("regions", [])
        boxes = geom_art.payload.get("boxes", [])

        page_num = getattr(context, "page_number", 1)

        page_w = 1000.0
        page_h = 1000.0
        if lines:
            page_w = float(lines[0].bbox.page_width or 1000.0)
            page_h = float(lines[0].bbox.page_height or 1000.0)
        elif boxes:
            page_w = float(boxes[0].bbox.page_width or 1000.0)
            page_h = float(boxes[0].bbox.page_height or 1000.0)

        # 1. Table Topology Resolver
        resolver = TableTopologyResolver()
        table_topologies = resolver.resolve_page_topology(
            page_number=page_num,
            boxes=regions,
            lines=lines,
            page_width=int(page_w),
            page_height=int(page_h)
        )

        # 1.5. Arabic Token Composition (ArabicTokenComposer)
        composer = ArabicTokenComposer()
        composed_tokens = composer.compose_page_tokens(ocr_art.payload)

        # 1.6. Logical Cell Grid Ownership (LogicalCellOwnershipResolver)
        ownership_resolver = LogicalCellOwnershipResolver()
        ownership_resolver.resolve_token_ownership(composed_tokens, table_topologies)
        ownership_resolver.resolve_region_ownership(regions, table_topologies)

        # 2. Region Hierarchy Inference
        hierarchy_inf = RegionHierarchyInference()
        hierarchy_records = hierarchy_inf.infer_hierarchy(
            page_number=page_num,
            page_width=int(page_w),
            page_height=int(page_h),
            table_topologies=table_topologies,
            flat_regions=regions
        )

        # 3. Checkbox Semantic Linker
        # Find checkboxes among spatial regions based on dimensions/aspect ratio
        checkbox_candidates = []
        for reg in regions:
            w = reg.bbox.x2 - reg.bbox.x1
            h = reg.bbox.y2 - reg.bbox.y1
            if 10.0 <= w <= 45.0 and 10.0 <= h <= 45.0 and 0.7 <= (w / h) <= 1.4:
                checkbox_candidates.append(reg)

        linker = CheckboxSemanticLinker(is_arabic=True)
        linked_checkboxes = linker.link_checkboxes(
            checkbox_candidates,
            composed_tokens,
            regions,
            lines
        )

        # 4. Arabic Reading Flow Stabilizer
        stabilizer = ArabicReadingFlowStabilizer()
        tokens = composed_tokens
        rows = self._group_tokens_into_rows(tokens)
        stabilized_tokens = []
        for row in rows:
            sorted_row = stabilizer.stabilize_row_tokens(row)
            stabilized_tokens.extend(sorted_row)

        # Save stabilized OCR tokens back to store as a new version of ocr_evidence
        stabilized_ocr_id = generate_stable_id("stabilized_ocr", ocr_art.artifact_id, len(stabilized_tokens))
        stabilized_ocr_art = PipelineArtifact(
            artifact_id=stabilized_ocr_id,
            artifact_type="ocr_evidence",
            derived_from=[ocr_art.artifact_id],
            payload=stabilized_tokens
        )
        store.save(stabilized_ocr_art)
        context.artifact_references["ocr_evidence"] = stabilized_ocr_id

        # Save topology payload
        payload = TopologyEvidencePayload(
            table_topologies=table_topologies,
            region_hierarchy=hierarchy_records,
            linked_checkboxes=linked_checkboxes
        )
        topo_art_id = generate_stable_id("topology", geom_art.artifact_id, len(table_topologies))
        topo_artifact = PipelineArtifact(
            artifact_id=topo_art_id,
            artifact_type="topology_evidence",
            derived_from=[geom_art.artifact_id, ocr_art.artifact_id],
            payload=payload
        )
        
        logger.info(f"TopologyStage completed: resolved {len(table_topologies)} tables, {len(hierarchy_records)} hierarchy nodes, linked {len(linked_checkboxes)} checkboxes.")
        return topo_artifact

    def _group_tokens_into_rows(self, tokens: List[Any], row_height_threshold: float = 12.0) -> List[List[Any]]:
        """Group tokens by visual rows based on y-coordinate proximity."""
        sorted_by_y = sorted(tokens, key=lambda t: t.bbox.y1)
        rows = []
        for t in sorted_by_y:
            placed = False
            for row in rows:
                row_y_center = sum((r.bbox.y1 + r.bbox.y2) / 2.0 for r in row) / len(row)
                tok_y_center = (t.bbox.y1 + t.bbox.y2) / 2.0
                if abs(tok_y_center - row_y_center) < row_height_threshold:
                    row.append(t)
                    placed = True
                    break
            if not placed:
                rows.append([t])
        return rows
