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
        try:
            table_topologies = resolver.resolve_page_topology(
                page_number=page_num,
                boxes=regions,
                lines=lines,
                page_width=int(page_w),
                page_height=int(page_h)
            )
        except Exception as topo_err:
            logger.error(f"TableTopologyResolver failed on page {page_num}: {topo_err}", exc_info=True)
            table_topologies = []

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

        # Create initial zones from geometry regions
        zones = []
        for reg in regions:
            w = reg.bbox.x2 - reg.bbox.x1
            h = reg.bbox.y2 - reg.bbox.y1
            
            # Smart classification
            zone_type = "unknown"
            if h < 45 and w > page_w * 0.2:
                # Short wide region is likely a section header or form title
                # Let's check if it's at the very top of the page (within first 15% height)
                if reg.bbox.y1 < page_h * 0.15:
                    zone_type = "form_title"
                else:
                    zone_type = "section_header"
            elif w > page_w * 0.7 and h > page_h * 0.5:
                zone_type = "free_text"
            elif w > page_w * 0.4 and h > 80:
                # Count checkboxes inside
                checkboxes_inside = 0
                for other in regions:
                    ow = other.bbox.x2 - other.bbox.x1
                    oh = other.bbox.y2 - other.bbox.y1
                    if 10.0 <= ow <= 45.0 and 10.0 <= oh <= 45.0 and 0.7 <= (ow / oh) <= 1.4:
                        if (reg.bbox.x1 - 5 <= other.bbox.x1 and other.bbox.x2 <= reg.bbox.x2 + 5 and
                            reg.bbox.y1 - 5 <= other.bbox.y1 and other.bbox.y2 <= reg.bbox.y2 + 5):
                            checkboxes_inside += 1
                
                if checkboxes_inside >= 2:
                    zone_type = "checkbox_group"
                else:
                    zone_type = "patient_info"
            
            include_in_form = zone_type not in {"section_header", "footer", "form_title"}
            zones.append({
                "zone_id": f"zone_{reg.stable_id[:8]}",
                "zone_type": zone_type,
                "zone_label": f"Zone {reg.stable_id[:6].upper()}",
                "bbox": [int(reg.bbox.x1), int(reg.bbox.y1), int(reg.bbox.x2), int(reg.bbox.y2)],
                "parent_zone_id": None,
                "confidence": float(reg.geometry_confidence or 1.0),
                "include_in_form": include_in_form,
            })

        # Apply zone operations from the ledger
        from app.services.hitl.operations_ledger import global_operations_ledger
        operations = global_operations_ledger.get_operations_for_run(context.run_id)
        for op in operations:
            if getattr(op, "operation_type", None) == "zone_operation":
                zone_op_type = getattr(op, "zone_op_type", None)
                target_zone_id = getattr(op, "target_zone_id", None)
                params = getattr(op, "parameters", {})
                
                if zone_op_type == "CREATE_ZONE":
                    if not any(z["zone_id"] == target_zone_id for z in zones):
                        z_type = params.get("zone_type", "unknown")
                        zones.append({
                            "zone_id": target_zone_id,
                            "zone_type": z_type,
                            "zone_label": params.get("zone_label", "Unnamed Zone"),
                            "bbox": params.get("bbox", [100, 100, 300, 200]),
                            "parent_zone_id": params.get("parent_zone_id"),
                            "confidence": 1.0,
                            "include_in_form": params.get("include_in_form", z_type not in {"section_header", "footer", "form_title"})
                        })
                elif zone_op_type == "DELETE_ZONE":
                    zones = [z for z in zones if z["zone_id"] != target_zone_id]
                elif zone_op_type == "RESIZE_ZONE":
                    for z in zones:
                        if z["zone_id"] == target_zone_id:
                            z["bbox"] = params.get("bbox", z["bbox"])
                elif zone_op_type == "RENAME_ZONE":
                    for z in zones:
                        if z["zone_id"] == target_zone_id:
                            if "zone_label" in params:
                                z["zone_label"] = params["zone_label"]
                            if "zone_type" in params:
                                z["zone_type"] = params["zone_type"]
                                z["include_in_form"] = params["zone_type"] not in {"section_header", "footer", "form_title"}
                elif zone_op_type == "SET_FORM_TITLE":
                    for z in zones:
                        if z["zone_id"] == target_zone_id:
                            z["zone_type"] = "form_title"
                            z["include_in_form"] = False
                            if "zone_label" in params:
                                z["zone_label"] = params["zone_label"]
                        elif z["zone_type"] == "form_title":
                            z["zone_type"] = "unknown"
                            z["include_in_form"] = True
                elif zone_op_type == "TOGGLE_INCLUDE":
                    for z in zones:
                        if z["zone_id"] == target_zone_id:
                            current = z.get("include_in_form", True)
                            z["include_in_form"] = params.get("include_in_form", not current)

        # ── SMART ZONE DISCOVERY (Token-Density + Anchor Calibration) ────────
        # Run SmartZoneDiscoveryEngine to discover zones from OCR token density
        # and apply anchor-based coordinate calibration. This runs AFTER geometry
        # zones are built so it can both add new zones AND calibrate existing ones.
        form_graph = None
        try:
            from app.core.forms.compiler import SmartZoneDiscoveryEngine, ZoneTypeClassifierEngine, StructuralSemanticCompilerEngine, resolve_zone_assignment
            from app.core.forms.models import (
                PageCompilationState, PageMetadata, OCREvidence, OCRWord,
                SemanticZone, ZoneType, BoundingBox as FormBBox,
                VisualPrimitiveEvidence, HierarchicalFieldPair, LinkStatus,
                SignalScores, PrimitiveType, Provenance
            )
            from datetime import datetime, timezone as tz
            import math

            def make_safe_bbox(x1, y1, x2, y2) -> FormBBox:
                x_min = max(0, int(x1))
                y_min = max(0, int(y1))
                x_max = max(x_min + 1, int(x2))
                y_max = max(y_min + 1, int(y2))
                return FormBBox(x_min=x_min, y_min=y_min, x_max=x_max, y_max=y_max)

            # Build minimal OCREvidence from stabilized tokens for the engine
            form_words = []
            for tok in stabilized_tokens:
                try:
                    form_words.append(OCRWord(
                        word_id=getattr(tok, "stable_id", str(id(tok))),
                        text=getattr(tok, "text", ""),
                        bbox=make_safe_bbox(tok.bbox.x1, tok.bbox.y1, tok.bbox.x2, tok.bbox.y2),
                        confidence=float(getattr(tok, "confidence", 0.9)),
                        direction="RTL" if getattr(tok, "is_rtl", False) else "LTR",
                    ))
                except Exception:
                    continue  # Skip malformed tokens

            # Build minimal SemanticZone list from existing geometry zones
            form_zones = []
            for z in zones:
                try:
                    bb = z["bbox"]
                    form_zones.append(SemanticZone(
                        zone_id=z["zone_id"],
                        zone_type=ZoneType(z.get("zone_type", "unknown"))
                            if z.get("zone_type", "unknown") in [e.value for e in ZoneType]
                            else ZoneType.UNKNOWN,
                        zone_label=z.get("zone_label", z["zone_id"]),
                        bbox=make_safe_bbox(bb[0], bb[1], bb[2], bb[3]),
                        confidence=float(z.get("confidence", 1.0)),
                    ))
                except Exception:
                    continue

            # Build VisualPrimitiveEvidence objects
            form_primitives = []
            # 1. Add checkboxes
            for cb in checkbox_candidates:
                cb_id = getattr(cb, "stable_id", getattr(cb, "cell_id", None))
                if cb_id:
                    form_primitives.append(VisualPrimitiveEvidence(
                        primitive_id=cb_id,
                        primitive_type=PrimitiveType.CHECKBOX,
                        bbox=make_safe_bbox(cb.bbox.x1, cb.bbox.y1, cb.bbox.x2, cb.bbox.y2),
                        confidence=float(getattr(cb, "geometry_confidence", 1.0) or 1.0)
                    ))
            # 2. Add lines (underlines)
            for line in lines:
                line_id = getattr(line, "stable_id", None)
                if line_id:
                    form_primitives.append(VisualPrimitiveEvidence(
                        primitive_id=line_id,
                        primitive_type=PrimitiveType.UNDERLINE_FIELD,
                        bbox=make_safe_bbox(line.bbox.x1, line.bbox.y1, line.bbox.x2, line.bbox.y2),
                        confidence=float(getattr(line, "confidence", 1.0) or 1.0)
                    ))

            # Build HierarchicalFieldPair list
            form_linked_fields = []
            for cb_id, linked_text in linked_checkboxes.items():
                cb_candidate = next((cb for cb in checkbox_candidates if getattr(cb, "stable_id", getattr(cb, "cell_id", None)) == cb_id), None)
                if not cb_candidate:
                    continue
                cb_bbox = cb_candidate.bbox
                cb_cx = (cb_bbox.x1 + cb_bbox.x2) / 2.0
                cb_cy = (cb_bbox.y1 + cb_bbox.y2) / 2.0

                best_tok = None
                min_dist = float("inf")
                for tok in stabilized_tokens:
                    if getattr(tok, "text", "") == linked_text:
                        tok_bbox = tok.bbox
                        tok_cx = (tok_bbox.x1 + tok_bbox.x2) / 2.0
                        tok_cy = (tok_bbox.y1 + tok_bbox.y2) / 2.0
                        dist = math.hypot(cb_cx - tok_cx, cb_cy - tok_cy)
                        if dist < min_dist:
                            min_dist = dist
                            best_tok = tok

                if best_tok:
                    tok_id = getattr(best_tok, "stable_id", None)
                    if tok_id:
                        assigned_zone_id = resolve_zone_assignment(
                            make_safe_bbox(cb_candidate.bbox.x1, cb_candidate.bbox.y1, cb_candidate.bbox.x2, cb_candidate.bbox.y2),
                            form_zones
                        )
                        prov = Provenance(
                            source_engine="CheckboxSemanticLinker",
                            confidence=1.0,
                            evidence_refs=[tok_id, cb_id],
                            creation_timestamp=datetime.now(tz.utc)
                        )
                        form_linked_fields.append(HierarchicalFieldPair(
                            pair_id=f"pair_{cb_id[:8]}_{tok_id[:8]}",
                            question_anchor_id=tok_id,
                            answer_node_id=cb_id,
                            status=LinkStatus.LINK_CONFIRMED,
                            signal_scores=SignalScores(final_score=1.0),
                            zone_id=assigned_zone_id or "unknown",
                            provenance=prov
                        ))

            if form_words:
                # Minimal PageMetadata for the engine
                meta = PageMetadata(
                    page_id=f"page_{context.run_id[:8]}",
                    document_id=context.document_id,
                    page_number=page_num,
                    width_px=max(1, int(page_w)),
                    height_px=max(1, int(page_h)),
                    dpi=300,
                    file_hash=context.run_id,
                    upload_timestamp=datetime.now(tz.utc),
                    pipeline_version=context.pipeline_version,
                )
                ocr_ev = OCREvidence(
                    words=form_words,
                    ocr_engine="paddleocr",
                    extraction_timestamp=datetime.now(tz.utc),
                )
                smart_state = PageCompilationState(
                    page_metadata=meta,
                    compiled_zones=form_zones,
                    ocr_evidence=ocr_ev,
                    visual_primitives=form_primitives,
                    linked_fields=form_linked_fields,
                    inferred_types=[],
                    composite_containers=[],
                    snapshots=[],
                    ledger_operations=[],
                )

                smart_engine = SmartZoneDiscoveryEngine(
                    v_gap_threshold=30,
                    h_gap_threshold=50,
                )
                smart_state = smart_engine.run(smart_state, operator_id="TopologyStage")

                # Merge newly discovered dynamic zones into the zones list
                existing_zone_ids = {z["zone_id"] for z in zones}
                for sz in smart_state.compiled_zones:
                    if sz.is_dynamic and sz.zone_id not in existing_zone_ids:
                        zones.append({
                            "zone_id": sz.zone_id,
                            "zone_type": sz.zone_type.value,
                            "zone_label": sz.zone_label,
                            "bbox": [
                                sz.bbox.x_min, sz.bbox.y_min,
                                sz.bbox.x_max, sz.bbox.y_max,
                            ],
                            "parent_zone_id": None,
                            "confidence": sz.detection_confidence,
                            "include_in_form": True,
                            "is_dynamic": True,
                            "coordinate_drift": sz.coordinate_drift,
                            "anchors_refs": sz.anchors_refs,
                            "direction": sz.metadata.get("direction", "RTL"),
                        })
                        existing_zone_ids.add(sz.zone_id)

                # Apply calibration drift to existing geometry zones
                for sz in smart_state.compiled_zones:
                    if sz.coordinate_drift is not None:
                        for z in zones:
                            if z["zone_id"] == sz.zone_id:
                                z["coordinate_drift"] = sz.coordinate_drift
                                z["anchors_refs"] = sz.anchors_refs
                                z["direction"] = sz.metadata.get("direction", z.get("direction", "RTL"))
                                break

                logger.info(
                    f"SmartZoneDiscoveryEngine added {len([z for z in zones if z.get('is_dynamic')])} "
                    f"dynamic zones. Total: {len(zones)} zones."
                )

                # ── تصنيف الـ zones من UNKNOWN إلى أنواع حقيقية ───────────────
                zone_classifier = ZoneTypeClassifierEngine()
                smart_state = zone_classifier.run(smart_state, operator_id="TopologyStage")

                for sz in smart_state.compiled_zones:
                    for z in zones:
                        if z["zone_id"] == sz.zone_id:
                            z["zone_type"] = sz.zone_type.value
                            break

                classified_count = sum(
                    1 for z in smart_state.compiled_zones
                    if z.zone_type != ZoneType.UNKNOWN
                )
                logger.info(
                    f"ZoneTypeClassifierEngine classified {classified_count}/{len(smart_state.compiled_zones)} zones."
                )

                # Compile structural semantic FormGraph
                try:
                    compiler = StructuralSemanticCompilerEngine()
                    compiled_state = compiler.run(smart_state)
                    form_graph = compiled_state.form_graph
                    logger.info("StructuralSemanticCompilerEngine successfully generated FormGraph.")
                except Exception as comp_err:
                    logger.error(f"StructuralSemanticCompilerEngine failed: {comp_err}")

        except Exception as smart_exc:
            # Smart discovery and Form compilation is non-critical — log and continue with geometry zones only
            logger.warning(f"SmartZoneDiscovery and Compiler skipped: {smart_exc}")

        # Save topology payload
        payload = TopologyEvidencePayload(
            table_topologies=table_topologies,
            region_hierarchy=hierarchy_records,
            linked_checkboxes=linked_checkboxes,
            zones=zones,
            form_graph=form_graph
        )
        topo_art_id = generate_stable_id("topology", geom_art.artifact_id, len(table_topologies))
        topo_artifact = PipelineArtifact(
            artifact_id=topo_art_id,
            artifact_type="topology_evidence",
            derived_from=[geom_art.artifact_id, ocr_art.artifact_id],
            payload=payload
        )
        
        logger.info(f"TopologyStage completed: resolved {len(table_topologies)} tables, {len(hierarchy_records)} hierarchy nodes, linked {len(linked_checkboxes)} checkboxes, compiled {len(zones)} zones.")
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
