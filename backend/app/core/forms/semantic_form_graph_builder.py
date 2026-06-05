"""
Semantic Form Graph Builder  — Phase 2 Form Understanding Layer

Combines LogicalTables, BoundQuestions, and standalone fields into a unified
SemanticFormGraph, which is the single source of truth for the Schema Builder.
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional

from app.core.forms.models import (
    BoundingBox,
    PageCompilationState,
    SemanticField,
    SemanticFormGraph,
    SemanticSection,
)
from app.services.schema.field_type_classifier import (
    classify_field_type,
    extract_nearby_label,
)

logger = logging.getLogger(__name__)


class SemanticFormGraphBuilder:
    """
    Builds the SemanticFormGraph by mapping layout elements to semantic concepts.
    """

    def build(
        self,
        state: PageCompilationState,
        logical_tables: List[Any],
        bound_questions: List[Any],
    ) -> SemanticFormGraph:
        """
        Synthesize SemanticFormGraph from logical topologies and bound fields.
        """
        page_id = state.page_metadata.page_id
        graph = SemanticFormGraph(page_id=page_id, sections=[], unassigned_fields=[])

        # Step 1: Initialize sections from compiled sections in FormGraph
        sections_map = {}
        if state.form_graph and state.form_graph.sections:
            for sec in state.form_graph.sections:
                # Find matching zone in state.compiled_zones to extract zone_type and inclusion status
                zone = next((z for z in state.compiled_zones if z.zone_id == sec.section_id), None)
                zone_type_val = "unknown"
                include_val = True
                if zone:
                    zone_type_val = zone.zone_type.value if hasattr(zone.zone_type, "value") else str(zone.zone_type)
                    if zone_type_val in {"section_header", "footer", "form_title"}:
                        include_val = False
                    if zone.metadata and "include_in_form" in zone.metadata:
                        include_val = zone.metadata["include_in_form"]
                
                s_section = SemanticSection(
                    section_id=sec.section_id,
                    label=sec.label,
                    fields=[],
                    bbox=sec.bbox,
                    zone_type=zone_type_val,
                    include_in_form=include_val,
                )
                graph.sections.append(s_section)
                sections_map[sec.section_id] = s_section
        else:
            # Fallback to compiled_zones of type SECTION_HEADER if form_graph sections are missing
            for zone in state.compiled_zones:
                if getattr(zone, "zone_type", None) == "section_header":
                    sec_id = f"sec_{zone.zone_id}"
                    zone_type_val = zone.zone_type.value if hasattr(zone.zone_type, "value") else str(zone.zone_type)
                    include_val = zone_type_val not in {"section_header", "footer", "form_title"}
                    s_section = SemanticSection(
                        section_id=sec_id,
                        label=zone.zone_label,
                        fields=[],
                        bbox=zone.bbox,
                        zone_type=zone_type_val,
                        include_in_form=include_val,
                    )
                    graph.sections.append(s_section)
                    sections_map[sec_id] = s_section

        # Step 2: Build coordinate/bbox lookup for all primitives and OCR words
        bbox_lookup = {}
        prim_types = {}
        for p in state.visual_primitives:
            bbox_lookup[p.primitive_id] = p.bbox
            prim_types[p.primitive_id] = p.primitive_type

        words_lookup = {}
        for w in (state.ocr_evidence.words if state.ocr_evidence else []):
            bbox_lookup[w.word_id] = w.bbox
            words_lookup[w.word_id] = w.text

        # Track which elements are already covered by checkboxes or tables
        covered_primitive_ids = set()

        # Step 3: Add Checkbox/Radio fields (BoundQuestions)
        all_fields = []
        for bq in bound_questions:
            field = SemanticField(
                field_id=bq.question_id,
                label=bq.question_text,
                field_type="enum",
                options=bq.options,
                bbox=bq.bbox,
                source="bound_question",
            )
            all_fields.append(field)

            # Mark all checkbox primitives as covered
            # Let's find child elements of the matching enum group in FormGraph to mark them
            for elem in state.form_graph.elements.values():
                if elem.bbox == bq.bbox:
                    for cid in elem.child_element_ids:
                        child_el = state.form_graph.elements.get(cid)
                        if child_el:
                            for pair_id in child_el.field_pairs:
                                pair = next((p for p in state.linked_fields if p.pair_id == pair_id), None)
                                if pair:
                                    covered_primitive_ids.add(pair.answer_node_id)

        # Step 4: Add Table fields (LogicalTables)
        for lt in logical_tables:
            # Mark all cells' primitives/regions as covered
            for cell in lt.cells:
                if cell.region_id:
                    covered_primitive_ids.add(cell.region_id)

            # Map cell grids: row 0 is columns header, row > 0 are data fields
            col_headers = {}
            for col in range(lt.col_count()):
                col_headers[col] = lt.col_header(col) or f"Column_{col}"

            for cell in lt.cells:
                if cell.is_header:
                    continue

                col_label = col_headers.get(cell.col, f"Column_{cell.col}")
                field_id = cell.region_id or f"cell_{lt.table_id}_{cell.row}_{cell.col}"

                # Snapping bbox tuple (x1, y1, x2, y2) to BoundingBox
                cell_bbox = BoundingBox(
                    x_min=int(cell.bbox[0]),
                    y_min=int(cell.bbox[1]),
                    x_max=int(cell.bbox[2]),
                    y_max=int(cell.bbox[3]),
                )

                ftype = classify_field_type(text=cell.text, nearby_label=col_label)
                field_type_str = ftype.value if hasattr(ftype, "value") else str(ftype)

                field = SemanticField(
                    field_id=field_id,
                    label=col_label,
                    field_type=field_type_str,
                    options=[],
                    bbox=cell_bbox,
                    source="table_cell",
                )
                all_fields.append(field)

        # Step 5: Add Standalone fields (HierarchicalFieldPairs not covered above)
        for pair in state.linked_fields:
            if pair.answer_node_id in covered_primitive_ids:
                continue

            ans_bbox = bbox_lookup.get(pair.answer_node_id)
            if not ans_bbox:
                continue

            # Resolve label using anchor text or nearby search
            label = words_lookup.get(pair.question_anchor_id)
            if not label and state.ocr_evidence:
                label = extract_nearby_label(
                    state.ocr_evidence.words,
                    [ans_bbox.x_min, ans_bbox.y_min, ans_bbox.x_max, ans_bbox.y_max],
                )

            if not label:
                label = f"Field_{pair.pair_id[:8]}"

            prim_type = prim_types.get(pair.answer_node_id)
            prim_type_str = prim_type.value if hasattr(prim_type, "value") else str(prim_type) if prim_type else None

            ftype = classify_field_type(
                text="", nearby_label=label, primitive_type=prim_type_str
            )
            field_type_str = ftype.value if hasattr(ftype, "value") else str(ftype)

            field = SemanticField(
                field_id=pair.pair_id,
                label=label,
                field_type=field_type_str,
                options=[],
                bbox=ans_bbox,
                source="free_field",
            )
            all_fields.append(field)

        # Step 6: Assign fields to sections (using spatial overlap check)
        for field in all_fields:
            f_cx = (field.bbox.x_min + field.bbox.x_max) / 2.0
            f_cy = (field.bbox.y_min + field.bbox.y_max) / 2.0

            best_sec = None
            for sec in graph.sections:
                # Check if field centroid is inside section bbox
                if (
                    sec.bbox.x_min <= f_cx <= sec.bbox.x_max
                    and sec.bbox.y_min <= f_cy <= sec.bbox.y_max
                ):
                    best_sec = sec
                    break

            if best_sec:
                field.section_id = best_sec.section_id
                best_sec.fields.append(field)
            else:
                graph.unassigned_fields.append(field)

        logger.info(
            "SemanticFormGraphBuilder: built graph with %d sections and %d unassigned fields.",
            len(graph.sections),
            len(graph.unassigned_fields),
        )
        return graph
