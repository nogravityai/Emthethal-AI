"""
Question-Control Binder  — Phase 2 Form Understanding Layer

Associates checkbox/radio option groups with their semantic question labels.
Produces BoundQuestion objects consumed by SemanticFormGraphBuilder.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from app.core.forms.models import PageCompilationState, FormElementType, BoundingBox

logger = logging.getLogger(__name__)


class BoundQuestion(BaseModel):
    """A checkbox/radio group bound to its resolved question label."""
    question_id: str
    question_text: str
    options: List[str]
    bbox: BoundingBox
    zone_id: str


class QuestionControlBinder:
    """
    Binds FormElementType.ENUM_GROUP checkbox elements to their visual question anchors.
    """

    def bind(
        self,
        state: PageCompilationState,
        logical_tables: Optional[List[Any]] = None,
    ) -> List[BoundQuestion]:
        """
        Binds enum/checkbox groups on the page to their nearest question text anchors.
        """
        if not state.form_graph or not state.ocr_evidence:
            return []

        ocr_words = state.ocr_evidence.words or []
        elements = state.form_graph.elements or {}

        # Collect table cell region IDs to exclude them from question anchors
        table_region_ids = set()
        if logical_tables:
            for t in logical_tables:
                for cell in t.cells:
                    if cell.region_id:
                        table_region_ids.add(cell.region_id)

        bound_questions: List[BoundQuestion] = []

        for elem_id, elem in elements.items():
            if elem.element_type != FormElementType.ENUM_GROUP:
                continue

            child_elems = [elements[cid] for cid in elem.child_element_ids if cid in elements]
            if not child_elems:
                continue

            option_texts = [child.label for child in child_elems]
            group_bbox = elem.bbox

            # Find the zone this group belongs to
            zone_id = "unknown"
            zone_ids = []
            for child in child_elems:
                for pair_id in child.field_pairs:
                    pair = next((p for p in state.linked_fields if p.pair_id == pair_id), None)
                    if pair:
                        zone_ids.append(pair.zone_id)
            if zone_ids:
                zone_id = max(set(zone_ids), key=zone_ids.count)

            # Identify words that are part of the options to filter them out
            option_bboxes = [child.bbox for child in child_elems]

            def _is_option_word(w: Any) -> bool:
                for opt_bbox in option_bboxes:
                    # Overlaps opt bbox
                    if w.bbox.intersection_area(opt_bbox) > 0 or w.bbox.contains(opt_bbox):
                        return True
                    # Close vertical and horizontal distance (adjacent label)
                    w_cy = (w.bbox.y_min + w.bbox.y_max) / 2.0
                    o_cy = (opt_bbox.y_min + opt_bbox.y_max) / 2.0
                    if abs(w_cy - o_cy) < 15:
                        if abs(w.bbox.x_min - opt_bbox.x_max) < 15 or abs(w.bbox.x_max - opt_bbox.x_min) < 15:
                            return True
                if w.text in option_texts:
                    return True
                return False

            candidate_words = [w for w in ocr_words if not _is_option_word(w)]

            # Locate candidates:
            # 1. RTL: right side of the options group
            # 2. Above the options group
            anchors = []
            group_cy = (group_bbox.y_min + group_bbox.y_max) / 2.0

            for w in candidate_words:
                w_cy = (w.bbox.y_min + w.bbox.y_max) / 2.0

                # Option 1: Right-hand side (RTL Arabic question prefix)
                if w.bbox.x_min >= group_bbox.x_min - 20:
                    if abs(w_cy - group_cy) < 25:
                        dist = w.bbox.x_min - group_bbox.x_max
                        if dist < 0:
                            dist = abs(dist)
                        anchors.append((dist, w))
                        continue

                # Option 2: Directly above (Header style question)
                if w.bbox.y_max <= group_bbox.y_min + 10:
                    h_overlap = max(0, min(group_bbox.x_max, w.bbox.x_max) - max(group_bbox.x_min, w.bbox.x_min))
                    if h_overlap > 0 or (w.bbox.x_min >= group_bbox.x_min - 100 and w.bbox.x_max <= group_bbox.x_max + 100):
                        dist = group_bbox.y_min - w.bbox.y_max
                        anchors.append((dist + 200, w))  # slight penalty to prioritize same-row right-side

            question_text = ""
            if anchors:
                anchors.sort(key=lambda x: x[0])
                best_w = anchors[0][1]

                # Group adjacent words on same visual line to form complete sentence
                best_cy = (best_w.bbox.y_min + best_w.bbox.y_max) / 2.0
                line_words = [
                    w for w in candidate_words
                    if abs((w.bbox.y_min + w.bbox.y_max) / 2.0 - best_cy) < 15
                ]
                # Sort RTL for Arabic reading order
                line_words.sort(key=lambda w: w.bbox.x_max, reverse=True)

                phrase_words = []
                for w in line_words:
                    # Restrict width context so we don't bleed into unrelated questions
                    if abs((w.bbox.x_min + w.bbox.x_max) / 2.0 - (best_w.bbox.x_min + best_w.bbox.x_max) / 2.0) < 400:
                        phrase_words.append(w.text)

                question_text = " ".join(phrase_words).strip()

            if not question_text:
                zone = next((z for z in state.compiled_zones if z.zone_id == zone_id), None)
                question_text = zone.zone_label if zone else f"Group_{elem_id[:8]}"

            bound_questions.append(BoundQuestion(
                question_id=f"bq_{elem_id[:8]}",
                question_text=question_text,
                options=option_texts,
                bbox=group_bbox,
                zone_id=zone_id
            ))

        logger.info("QuestionControlBinder: bound %d checkbox/radio question(s).", len(bound_questions))
        return bound_questions
