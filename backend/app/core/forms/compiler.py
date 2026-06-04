from __future__ import annotations
import logging
import math
import json
import hashlib
import re
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Union, Tuple, Literal
from pydantic import BaseModel, Field
from enum import Enum

# Import models defined in models.py
from app.core.forms.models import (
    PageCompilationState,
    PageMetadata,
    OCREvidence,
    OCRWord,
    VisualPrimitiveEvidence,
    SemanticZoneProposal,
    FieldGroupCandidate,
    AnchorCandidate,
    ValueCandidate,
    LayoutGrammarGraph,
    ReadingOrderSequence,
    ReadingOrderEntry,
    HierarchicalFieldPair,
    SignalScores,
    SemanticZone,
    FieldType,
    SnapResult,
    FieldTypeInference,
    CompositeFieldContainer,
    ContainerInstance,
    ContainerValidationStatus,
    CanonicalFieldMapping,
    CrossFieldConstraint,
    ConstraintGraph,
    ValidationReport,
    FieldViolation,
    ConstraintViolation,
    TentativeLinkBatch,
    BaseLedgerOperation,
    LedgerOperation,
    ZoneOperation,
    FieldOperation,
    RelationshipOperation,
    ContainerOperation,
    TentativeLinkResolutionOperation,
    CompensateOperation,
    DraftOperation,
    CompiledSnapshot,
    SchemaMigrationAdapter,
    ProcessingError,
    ProcessingSeverity,
    SnapshotRaceConditionError,
    DeterminismViolationAlert,
    FormTemplate,
    TemplateFailureLog,
    PageExtractionResult,
    OrchestrationContract,
    BoundingBox,
    PrimitiveType,
    ZoneType,
    LinkStatus,
    Provenance,
    FormGraph,
    FormElement,
    FormSection,
    StructuralEdge,
    StructuralConstraint,
    FormElementType,
    LayoutTopologyType,
    StructuralRelationType,
    ConstraintType,
    TopologySignature
)

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────
# ZONE COLLISION RESOLUTION PROTOCOL (RULE 4)
# ────────────────────────────────────────────────────────────

def resolve_zone_assignment(
    element_bbox: BoundingBox,
    zones: List[SemanticZone],
    drift_offset: Optional[Tuple[float, float]] = None,
) -> Optional[str]:
    """
    Deterministic Zone Collision Resolution Protocol as specified in RULE 4.

    drift_offset (dx, dy):
        If provided (set by AnchorCalibrationEngine), the element's coordinates are
        shifted by (dx, dy) *before* the containment / overlap checks.  This lets
        the system compensate for scanning/printing drift without mutating the
        immutable OCR evidence. The shift is applied only locally inside this call;
        the original BoundingBox is never modified.
    """
    if not zones:
        return None

    # Apply calibration offset to a virtual bbox (keeps OCR evidence immutable)
    if drift_offset is not None:
        dx, dy = drift_offset
        shifted_x_min = max(0, int(element_bbox.x_min + dx))
        shifted_y_min = max(0, int(element_bbox.y_min + dy))
        shifted_x_max = max(shifted_x_min + 1, int(element_bbox.x_max + dx))
        shifted_y_max = max(shifted_y_min + 1, int(element_bbox.y_max + dy))
        effective_bbox = BoundingBox(
            x_min=shifted_x_min, y_min=shifted_y_min,
            x_max=shifted_x_max, y_max=shifted_y_max,
        )
    else:
        effective_bbox = element_bbox

    # Priority 1: STRICT_CONTAINMENT — fully contained in exactly ONE zone
    containing_zones = [z for z in zones if z.bbox.contains(effective_bbox)]
    if len(containing_zones) == 1:
        return containing_zones[0].zone_id

    # If not strictly contained in exactly one, consider all overlapping candidates
    overlapping_candidates = []
    for z in zones:
        inter_area = z.bbox.intersection_area(effective_bbox)
        if inter_area > 0 or z.bbox.contains(effective_bbox):
            overlapping_candidates.append(z)

    if not overlapping_candidates:
        return None

    # Helper to compute tree depth
    zone_dict = {z.zone_id: z for z in zones}
    def get_depth(z: SemanticZone) -> int:
        depth = 0
        curr = z
        visited = set()
        while curr.parent_zone_id and curr.parent_zone_id in zone_dict:
            if curr.parent_zone_id in visited:
                break  # Cycle safety
            visited.add(curr.parent_zone_id)
            depth += 1
            curr = zone_dict[curr.parent_zone_id]
        return depth

    # Priority sorting helper — best candidate ends up at index -1
    # Keys (ascending → last element wins):
    #   1. Contained in shifted bbox (1 > 0)
    #   2. Deepest tree level (larger depth wins)
    #   3. Smallest area (-area, so smaller wins)
    #   4. Highest overlap ratio (intersection / effective_bbox area)
    #   5. Alphabetical fallback (lexicographic descending sort applied first)
    overlapping_candidates.sort(key=lambda z: z.zone_id, reverse=True)

    def priority_key(z: SemanticZone):
        contained = 1 if z.bbox.contains(effective_bbox) else 0
        depth = get_depth(z)
        area = z.bbox.area()
        inter_area = z.bbox.intersection_area(effective_bbox)
        elem_area = effective_bbox.area()
        overlap_ratio = inter_area / elem_area if elem_area > 0 else 0.0
        return (contained, depth, -area, overlap_ratio)

    overlapping_candidates.sort(key=priority_key)
    return overlapping_candidates[-1].zone_id


# ────────────────────────────────────────────────────────────
# 1.3 PrimitiveShapeDetectorEngine (UNDERLINE vs TEXTLINE)
# ────────────────────────────────────────────────────────────

class PrimitiveShapeDetectorEngine:
    """
    Detects primitives and performs underline_field vs text-line disambiguation (Gap#36).
    """
    def run(self, candidates: List[VisualPrimitiveEvidence], ocr_words: List[OCRWord]) -> List[VisualPrimitiveEvidence]:
        disambiguated = []
        for prim in candidates:
            # Only perform disambiguation for candidate UNDERLINE_FIELD
            if prim.primitive_type == PrimitiveType.UNDERLINE_FIELD:
                disambiguation_applied = False
                contains_ocr_words = False
                
                # Check for overlapping OCRWords with overlap_ratio > 0.5 and confidence > 0.5
                for word in ocr_words:
                    word_area = word.bbox.area()
                    if word_area <= 0:
                        continue
                    inter_area = prim.bbox.intersection_area(word.bbox)
                    overlap_ratio = inter_area / word_area
                    if overlap_ratio > 0.5 and word.confidence > 0.5:
                        disambiguation_applied = True
                        contains_ocr_words = True
                        break
                
                if disambiguation_applied:
                    # Reclassify as TEXTLINE
                    metadata = prim.detection_metadata
                    new_metadata = metadata.model_copy(update={
                        "contains_ocr_words": True,
                        "edge_density": getattr(metadata, "edge_density", None)
                    })
                    # Set extra field on metadata if dictionary-based, or model field
                    # models.py has contains_ocr_words on DetectionMetadata, and disambiguation_applied on models.py?
                    # Let's inspect: BoundingBox, PrimitiveType, etc.
                    # Wait, let's see if models.py is flexible enough.
                    # models.py Section 5:
                    # class DetectionMetadata(BaseModel):
                    #     edge_density: Optional[float] = None
                    #     fill_ratio: Optional[float] = None
                    #     contour_area: float = 0.0
                    #     aspect_ratio: float = 0.0
                    #     num_hough_lines: int = 0
                    #     is_filled: bool = False
                    #     contains_ocr_words: bool = False
                    
                    # Let's verify if we can set it.
                    # In models.py we saw:
                    # Line 301: # underline_field disambiguation (closes Gap#36):
                    # Line 302: # underline_field is only assigned when contains_ocr_words is False.
                    # Line 303: # If a horizontal line's bbox overlaps OCRWords with confidence > 0.5,
                    # Line 304: # it is classified as TEXTLINE, not UNDERLINE_FIELD.
                    # Line 305: disambiguation_applied: bool = False
                    
                    # Ah! line 305 has "disambiguation_applied: bool = False" inside DetectionMetadata!
                    # Yes! It is a field in DetectionMetadata.
                    
                    # Create copy with modified values
                    new_prim = prim.model_copy(update={
                        "primitive_type": PrimitiveType.TEXTLINE,
                        "detection_metadata": new_metadata.model_copy(update={
                            "contains_ocr_words": True,
                            "is_filled": getattr(new_metadata, "is_filled", False)
                        })
                    })
                    # We can set disambiguation_applied if it is in detection_metadata
                    if hasattr(new_prim.detection_metadata, "disambiguation_applied"):
                        setattr(new_prim.detection_metadata, "disambiguation_applied", True)
                    disambiguated.append(new_prim)
                else:
                    disambiguated.append(prim)
            else:
                disambiguated.append(prim)
        return disambiguated


# ────────────────────────────────────────────────────────────
# 1.12 ReadingOrderEngine (Gap#8)
# ────────────────────────────────────────────────────────────

class ReadingOrderEngine:
    """
    Computes deterministic word reading order across all zones on the page.
    Also calculates median_line_height_px per zone.
    """
    def run(self, ocr_evidence: OCREvidence, zones: List[SemanticZone]) -> Tuple[ReadingOrderSequence, List[SemanticZone]]:
        entries = []
        updated_zones = []
        
        # Group words by zone
        words_by_zone: Dict[str, List[OCRWord]] = {}
        for z in zones:
            words_by_zone[z.zone_id] = []
            
        unassigned_words = []
        for word in ocr_evidence.words:
            assigned_zone_id = resolve_zone_assignment(word.bbox, zones)
            if assigned_zone_id:
                words_by_zone[assigned_zone_id].append(word)
            else:
                unassigned_words.append(word)

        for z in zones:
            words = words_by_zone[z.zone_id]
            if not words:
                updated_zones.append(z.model_copy(update={"median_line_height_px": None}))
                continue

            # 1. Cluster words into lines vertically
            # Sort words by vertical top coordinate
            sorted_words = sorted(words, key=lambda w: w.bbox.y_min)
            lines: List[List[OCRWord]] = []
            
            for w in sorted_words:
                y_center = (w.bbox.y_min + w.bbox.y_max) / 2.0
                h = w.bbox.y_max - w.bbox.y_min
                placed = False
                for line in lines:
                    line_y_center = sum((item.bbox.y_min + item.bbox.y_max)/2.0 for item in line) / len(line)
                    line_h_avg = sum(item.bbox.y_max - item.bbox.y_min for item in line) / len(line)
                    # Word overlaps line if centers are closer than 40% of line average height
                    if abs(y_center - line_y_center) < max(8.0, 0.4 * line_h_avg):
                        line.append(w)
                        placed = True
                        break
                if not placed:
                    lines.append([w])

            # 2. Sort lines vertically and words horizontally within each line
            lines.sort(key=lambda line: sum(w.bbox.y_min for w in line) / len(line))
            
            # Determine direction (RTL or LTR)
            direction = ocr_evidence.page_direction
            if z.metadata and "direction" in z.metadata:
                direction = z.metadata["direction"]

            # Calculate word/line heights for median
            word_heights = []
            
            for line_idx, line in enumerate(lines):
                # Sort horizontally: LTR -> ascending x_min; RTL -> descending x_min
                if direction == "RTL":
                    line.sort(key=lambda w: w.bbox.x_min, reverse=True)
                else:
                    line.sort(key=lambda w: w.bbox.x_min)
                
                for pos_idx, word in enumerate(line):
                    word_heights.append(word.bbox.y_max - word.bbox.y_min)
                    entries.append(ReadingOrderEntry(
                        word_id=word.word_id,
                        line_index=line_idx,
                        position_in_line=pos_idx,
                        resolved_direction=direction,
                        zone_id=z.zone_id
                    ))

            # Compute median line height
            if word_heights:
                word_heights.sort()
                n = len(word_heights)
                if n % 2 == 1:
                    median_height = float(word_heights[n // 2])
                else:
                    median_height = float((word_heights[n // 2 - 1] + word_heights[n // 2]) / 2.0)
            else:
                median_height = None
                
            updated_zones.append(z.model_copy(update={"median_line_height_px": median_height}))

        # Handle unassigned words (if any, place in dummy line of a special "unassigned" zone)
        for idx, word in enumerate(unassigned_words):
            entries.append(ReadingOrderEntry(
                word_id=word.word_id,
                line_index=0,
                position_in_line=idx,
                resolved_direction=ocr_evidence.page_direction,
                zone_id="unassigned"
            ))

        reading_order = ReadingOrderSequence(
            entries=entries,
            page_id=ocr_evidence.words[0].word_id.split("_")[0] if ocr_evidence.words else "page",
            computed_at=datetime.now(timezone.utc)
        )
        return reading_order, updated_zones


# ────────────────────────────────────────────────────────────
# OPTION ELEMENT LABEL RESOLUTION (Gap#37)
# ────────────────────────────────────────────────────────────

def resolve_option_element_label(
    opt_elem_bbox: BoundingBox,
    ocr_words: List[OCRWord],
    primitives: List[VisualPrimitiveEvidence],
    direction: Literal["LTR", "RTL"] = "LTR"
) -> Tuple[Optional[str], List[str]]:
    """
    Search for label words within a 20px horizontal margin to the right (LTR) or left (RTL).
    Return label text and corresponding word IDs.
    """
    # 1. Define horizontal margin box
    if direction == "LTR":
        # 20px margin to the right
        margin_bbox = BoundingBox(
            x_min=opt_elem_bbox.x_max,
            y_min=opt_elem_bbox.y_min,
            x_max=opt_elem_bbox.x_max + 20,
            y_max=opt_elem_bbox.y_max
        )
    else:
        # 20px margin to the left
        margin_bbox = BoundingBox(
            x_min=max(0, opt_elem_bbox.x_min - 20),
            y_min=opt_elem_bbox.y_min,
            x_max=opt_elem_bbox.x_min,
            y_max=opt_elem_bbox.y_max
        )

    # 2. Find overlapping OCRWords
    candidate_words = []
    for word in ocr_words:
        if margin_bbox.intersection_area(word.bbox) > 0 or margin_bbox.contains(word.bbox):
            # Check if this word overlaps another primitive's bbox (excluding the source box)
            overlaps_other = False
            for prim in primitives:
                if prim.bbox.contains(word.bbox) or prim.bbox.intersection_area(word.bbox) > 0:
                    # Ignore if it is a different bounding box
                    if prim.bbox.iou(opt_elem_bbox) < 0.9:
                        overlaps_other = True
                        break
            if not overlaps_other:
                candidate_words.append(word)

    if not candidate_words:
        return None, []

    # Sort candidates by spatial distance to opt_elem_bbox
    # Distance is horizontal distance
    def word_distance(w: OCRWord):
        if direction == "LTR":
            dist = w.bbox.x_min - opt_elem_bbox.x_max
        else:
            dist = opt_elem_bbox.x_min - w.bbox.x_max
        return (dist, -w.confidence) # tie-breaker: higher confidence wins

    candidate_words.sort(key=word_distance)
    
    # Take the words, group them, and return text
    # Sort candidate words horizontally before joining text
    if direction == "RTL":
        candidate_words.sort(key=lambda w: w.bbox.x_min, reverse=True)
    else:
        candidate_words.sort(key=lambda w: w.bbox.x_min)

    label_text = " ".join(w.text for w in candidate_words)
    label_ids = [w.word_id for w in candidate_words]
    return label_text, label_ids


# ────────────────────────────────────────────────────────────
# SMART ZONE DISCOVERY ENGINE  [Phase-3 Smart Orchestration]
# ────────────────────────────────────────────────────────────

import re
import uuid


class SmartZoneDiscoveryEngine:
    """
    Bridges the Token layer and the Zone layer through three tightly integrated
    sub-systems:

    1. Token-Density Clustering (_cluster_tokens_into_zones)
       Groups nearby OCR words into candidate zone bounding-boxes by scanning
       vertical/horizontal proximity gaps.  No ML model is required — the only
       inputs are the immutable OCREvidence words and two tunable gap thresholds.

    2. Anchor-Based Coordinate Calibration (_calibrate_anchors)
       For each zone that declares anchor_keywords, the engine searches the live
       OCR word list for matching tokens.  It then computes the mean (Δx, Δy)
       between where the template says the anchor should be and where the OCR
       actually found it.  The drift is stored on the SemanticZone
       (coordinate_drift) and written to the ledger as a CALIBRATE_COORDINATES
       operation so every calibration event is fully auditable.

    3. Adaptive Reading-Direction Detection (_detect_zone_direction)
       Counts RTL vs LTR tokens inside each candidate zone and assigns the
       dominant direction to zone.metadata["direction"].  This value is later
       consumed by ReadingOrderEngine when it sorts tokens within the zone.

    Usage
    -----
    engine = SmartZoneDiscoveryEngine(
        v_gap_threshold=20,   # px — maximum vertical gap between two words in the same line cluster
        h_gap_threshold=40,   # px — maximum horizontal gap between two words on the same row
        anchor_keywords={      # optional: zone_label -> list of keyword strings to look for
            "patient_info": ["اسم المريض", "Patient Name", "المريض"],
        },
    )
    new_state = engine.run(state, operator_id="system")
    """

    # ── Default anchor keywords (Arabic / English medical form labels) ──────
    DEFAULT_ANCHOR_KEYWORDS: Dict[str, List[str]] = {
        "patient_info":    ["اسم المريض", "Patient Name", "الاسم", "Name"],
        "section_header":  ["القسم", "Section", "Department"],
        "signature_block": ["التوقيع", "Signature", "توقيع"],
        "footer":          ["ملاحظات", "Notes", "Remarks"],
    }

    def __init__(
        self,
        v_gap_threshold: float = 20.0,
        h_gap_threshold: float = 40.0,
        anchor_keywords: Optional[Dict[str, List[str]]] = None,
    ):
        self.v_gap_threshold = v_gap_threshold
        self.h_gap_threshold = h_gap_threshold
        self.anchor_keywords: Dict[str, List[str]] = (
            anchor_keywords if anchor_keywords is not None
            else self.DEFAULT_ANCHOR_KEYWORDS
        )

    # ── Public entry point ────────────────────────────────────────────────────

    def run(
        self,
        state: "PageCompilationState",
        operator_id: str = "SmartZoneDiscoveryEngine",
    ) -> "PageCompilationState":
        """
        Orchestrates the three sub-systems and returns an updated
        PageCompilationState.  Only zones that are *already in*
        state.compiled_zones are mutated — the engine never silently
        creates zones without emitting a ledger operation.

        New dynamic zones discovered from clustering are added via
        CREATE_ZONE ledger operations so the full audit trail is
        preserved.
        """
        if not state.ocr_evidence:
            logger.warning("SmartZoneDiscoveryEngine: no OCR evidence in state; skipping.")
            return state

        ocr_words: List[OCRWord] = state.ocr_evidence.words
        current_zones: List[SemanticZone] = list(state.compiled_zones)
        ledger_ops: List[Any] = list(state.ledger_operations)
        seq = len(ledger_ops)

        # ── Step 1: discover candidate zones from token density ────────────
        candidate_zones = self._cluster_tokens_into_zones(
            ocr_words, state.page_metadata.page_id
        )

        # Emit CREATE_ZONE for every genuinely new candidate
        existing_ids = {z.zone_id for z in current_zones}
        for cz in candidate_zones:
            if cz.zone_id not in existing_ids:
                op = ZoneOperation(
                    operation_id=str(uuid.uuid4()),
                    ledger_sequence_number=seq,
                    timestamp=datetime.now(timezone.utc),
                    operator_id=operator_id,
                    operation_type="CREATE_ZONE",
                    target_zone_id=cz.zone_id,
                    parameters={
                        "zone_type": cz.zone_type.value,
                        "zone_label": cz.zone_label,
                        "bbox": cz.bbox.model_dump(),
                        "metadata": cz.metadata,
                        "is_dynamic": True,
                        "detection_confidence": cz.detection_confidence,
                    },
                    previous_state={},
                )
                ledger_ops.append(op)
                current_zones.append(cz)
                existing_ids.add(cz.zone_id)
                seq += 1

        # ── Step 2: anchor calibration for all zones ───────────────────────
        calibrated_zones: List[SemanticZone] = []
        for zone in current_zones:
            zone_label_key = zone.zone_label.lower().replace(" ", "_")
            keywords = self.anchor_keywords.get(
                zone_label_key,
                self.anchor_keywords.get(zone.zone_type.value, [])
            )
            if not keywords:
                calibrated_zones.append(zone)
                continue

            drift, anchor_word_ids = self._calibrate_anchors(
                zone, ocr_words, keywords
            )
            if drift is None:
                calibrated_zones.append(zone)
                continue

            dx, dy = drift
            # Record drift on the zone model
            updated_zone = zone.model_copy(update={
                "coordinate_drift": (dx, dy),
                "anchors_refs": anchor_word_ids,
            })
            calibrated_zones.append(updated_zone)

            # Write CALIBRATE_COORDINATES to ledger
            cal_op = ZoneOperation(
                operation_id=str(uuid.uuid4()),
                ledger_sequence_number=seq,
                timestamp=datetime.now(timezone.utc),
                operator_id=operator_id,
                operation_type="CALIBRATE_COORDINATES",
                target_zone_id=zone.zone_id,
                parameters={
                    "dx": dx,
                    "dy": dy,
                    "anchor_word_ids": anchor_word_ids,
                },
                previous_state={
                    "coordinate_drift": None,
                    "anchors_refs": zone.anchors_refs,
                },
            )
            ledger_ops.append(cal_op)
            seq += 1

            logger.info(
                "SmartZoneDiscoveryEngine: zone=%s drift=(%.1f, %.1f) "
                "anchors=%s",
                zone.zone_id, dx, dy, anchor_word_ids,
            )

        # ── Step 3: detect dominant reading direction per zone ─────────────
        direction_updated_zones: List[SemanticZone] = []
        for zone in calibrated_zones:
            direction = self._detect_zone_direction(zone, ocr_words)
            new_meta = {**zone.metadata, "direction": direction}
            direction_updated_zones.append(
                zone.model_copy(update={"metadata": new_meta})
            )

        # ── Persist back into state ────────────────────────────────────────
        new_state = state.model_copy(update={
            "compiled_zones": direction_updated_zones,
            "ledger_operations": ledger_ops,
        })
        return new_state

    # ── Sub-system 1: Token-Density Clustering ────────────────────────────

    def _cluster_tokens_into_zones(
        self,
        words: List[OCRWord],
        page_id: str,
    ) -> List[SemanticZone]:
        """
        Groups OCR words into rectangular clusters using a single-link
        proximity sweep:
          - Words are sorted by y_min then x_min.
          - A word joins an existing cluster if its vertical distance to the
            cluster's y_max is ≤ v_gap_threshold AND its horizontal distance
            to the cluster's x range is ≤ h_gap_threshold.
          - Otherwise a new cluster is started.

        Each cluster becomes a candidate SemanticZone with is_dynamic=True.
        The zone_type defaults to UNKNOWN; downstream engines (LayoutLMv3,
        template matching) refine it.
        """
        if not words:
            return []

        sorted_words = sorted(words, key=lambda w: (w.bbox.y_min, w.bbox.x_min))

        # Each cluster: {"words": [...], "x_min", "y_min", "x_max", "y_max"}
        clusters: List[Dict[str, Any]] = []

        for word in sorted_words:
            placed = False
            for cluster in clusters:
                v_dist = word.bbox.y_min - cluster["y_max"]
                # Horizontal overlap or proximity check
                h_overlap = not (
                    word.bbox.x_max < cluster["x_min"] - self.h_gap_threshold
                    or word.bbox.x_min > cluster["x_max"] + self.h_gap_threshold
                )
                if 0 <= v_dist <= self.v_gap_threshold and h_overlap:
                    cluster["words"].append(word)
                    cluster["x_min"] = min(cluster["x_min"], word.bbox.x_min)
                    cluster["y_min"] = min(cluster["y_min"], word.bbox.y_min)
                    cluster["x_max"] = max(cluster["x_max"], word.bbox.x_max)
                    cluster["y_max"] = max(cluster["y_max"], word.bbox.y_max)
                    placed = True
                    break
            if not placed:
                clusters.append({
                    "words":  [word],
                    "x_min":  word.bbox.x_min,
                    "y_min":  word.bbox.y_min,
                    "x_max":  word.bbox.x_max,
                    "y_max":  word.bbox.y_max,
                })

        # Convert clusters → SemanticZone candidates
        zone_candidates: List[SemanticZone] = []
        for idx, cluster in enumerate(clusters):
            if len(cluster["words"]) < 2:
                # Single-word clusters are noise; skip
                continue

            # Confidence: proportional to word count (capped at 1.0)
            confidence = min(1.0, len(cluster["words"]) / 10.0)

            bbox = BoundingBox(
                x_min=cluster["x_min"],
                y_min=cluster["y_min"],
                x_max=max(cluster["x_min"] + 1, cluster["x_max"]),
                y_max=max(cluster["y_min"] + 1, cluster["y_max"]),
            )
            zone_id = f"dyn_{page_id}_cluster_{idx:03d}"
            zone_candidates.append(
                SemanticZone(
                    zone_id=zone_id,
                    zone_type=ZoneType.UNKNOWN,
                    zone_label=f"auto_cluster_{idx:03d}",
                    bbox=bbox,
                    confidence=confidence,
                    is_dynamic=True,
                    detection_confidence=confidence,
                    metadata={"word_count": len(cluster["words"])},
                )
            )

        return zone_candidates

    # ── Sub-system 2: Anchor-Based Coordinate Calibration ─────────────────

    def _calibrate_anchors(
        self,
        zone: SemanticZone,
        words: List[OCRWord],
        keywords: List[str],
    ) -> Tuple[Optional[Tuple[float, float]], List[str]]:
        """
        Finds anchor words inside or near the zone bbox that match any of the
        given keywords (case-insensitive, strip diacritics).

        Returns:
          (dx, dy) — mean coordinate drift between zone center and matched
                     anchor token center.  None if no anchors found.
          [word_ids] — IDs of the matched anchor tokens.

        The zone template is assumed to be the `zone.bbox`; the actual OCR
        token position is the ground truth.  So:
            dx = actual_anchor_cx - zone_bbox_cx
            dy = actual_anchor_cy - zone_bbox_cy
        """
        zone_cx, zone_cy = zone.bbox.center

        # Expand search radius to 1.5× the zone height/width
        h = zone.bbox.y_max - zone.bbox.y_min
        w = zone.bbox.x_max - zone.bbox.x_min
        search_bbox = BoundingBox(
            x_min=max(0, zone.bbox.x_min - w // 2),
            y_min=max(0, zone.bbox.y_min - h // 2),
            x_max=zone.bbox.x_max + w // 2,
            y_max=zone.bbox.y_max + h // 2,
        )

        # Normalise keywords for fuzzy matching
        def _normalise(text: str) -> str:
            # Strip Arabic diacritics (harakat)
            text = re.sub(r'[\u064B-\u065F\u0670]', '', text)
            return text.strip().lower()

        normalised_keywords = [_normalise(k) for k in keywords]

        matched_words: List[OCRWord] = []
        for word in words:
            # Must be inside expanded search bbox
            if search_bbox.intersection_area(word.bbox) == 0 and not search_bbox.contains(word.bbox):
                continue
            norm_word = _normalise(word.text)
            for kw in normalised_keywords:
                if kw in norm_word or norm_word in kw:
                    matched_words.append(word)
                    break

        if not matched_words:
            return None, []

        # Compute mean drift
        dx_total, dy_total = 0.0, 0.0
        for mw in matched_words:
            ax, ay = mw.bbox.center
            dx_total += ax - zone_cx
            dy_total += ay - zone_cy

        n = len(matched_words)
        dx = dx_total / n
        dy = dy_total / n
        anchor_ids = [mw.word_id for mw in matched_words]
        return (dx, dy), anchor_ids

    # ── Sub-system 3: Adaptive Reading-Direction Detection ────────────────

    def _detect_zone_direction(
        self,
        zone: SemanticZone,
        words: List[OCRWord],
    ) -> Literal["LTR", "RTL"]:
        """
        Counts RTL-tagged vs LTR-tagged OCR words whose bbox overlaps the
        zone bbox.  Returns the dominant direction; defaults to LTR on a tie.
        """
        rtl_count = 0
        ltr_count = 0
        for word in words:
            if zone.bbox.intersection_area(word.bbox) > 0 or zone.bbox.contains(word.bbox):
                if getattr(word, "direction", "LTR") == "RTL":
                    rtl_count += 1
                else:
                    ltr_count += 1

        return "RTL" if rtl_count > ltr_count else "LTR"


# ────────────────────────────────────────────────────────────
# 1.15 ZoneTypeClassifierEngine  [Phase-3 Smart Orchestration]
# ────────────────────────────────────────────────────────────

class ZoneTypeClassifierEngine:
    """
    يُصنّف الـ SemanticZones من ZoneType.UNKNOWN إلى أنواعها الصحيحة.
    يعمل مباشرةً بعد SmartZoneDiscoveryEngine وقبل StructuralSemanticCompilerEngine.

    خوارزمية التصنيف (بالأولوية):
      1. إذا احتوت الـ zone على CHECKBOX/RADIO_BUTTON primitives → CHECKBOX_GROUP
      2. إذا تطابق النص مع أنماط العناوين الأقسام (رقم + نقطة، أو مفتاح عربي) → SECTION_HEADER
      3. إذا تطابق النص مع كلمات التوقيع → SIGNATURE_BLOCK
      4. إذا تطابق النص مع كلمات التذييل → FOOTER
      5. Zone صغيرة (< 40px) بدون نص → CHECKBOX_GROUP مؤقتة
      6. Zone عريضة بنص كثيف → FREE_TEXT
      7. باقي الحالات → UNKNOWN (للمراجعة اليدوية)
    """

    # ── أنماط عناوين الأقسام ──────────────────────────────────────────────────
    _SECTION_PATTERNS = [
        re.compile(r'^\d+[\.\-\)]\s*', re.UNICODE),           # "1." "2-" "3)"
        re.compile(r'^(القسم|البند|الجزء|الفصل)\s*', re.UNICODE),
        re.compile(r'^(أولاً|ثانياً|ثالثاً|رابعاً|خامساً)\s*', re.UNICODE),
        re.compile(r'^(بيانات|معلومات|تفاصيل)\s+', re.UNICODE),  # "بيانات المريض"
    ]

    # ── كلمات مفتاحية للتوقيع والتذييل ────────────────────────────────────────
    _SIGNATURE_KW = frozenset(['التوقيع', 'توقيع', 'الختم', 'ختم', 'Signature', 'اعتمد', 'المراجع'])
    _FOOTER_KW    = frozenset(['ملاحظات', 'Notes', 'Remarks', 'تاريخ التحرير', 'Date', 'رقم الاستمارة'])

    def run(
        self,
        state: "PageCompilationState",
        operator_id: str = "ZoneTypeClassifierEngine",
    ) -> "PageCompilationState":
        """
        يمر على جميع الـ zones، ويُصنّف كل UNKNOWN zone بناءً على السياق.
        يُدوّن كل تصنيف كـ ZoneOperation في الـ ledger للتتبع الكامل.
        """
        if not state.compiled_zones:
            return state

        ocr_words: List[OCRWord] = state.ocr_evidence.words if state.ocr_evidence else []
        primitives: List[VisualPrimitiveEvidence] = list(state.visual_primitives)

        updated_zones: List[SemanticZone] = []
        ledger_ops: List[Any] = list(state.ledger_operations)
        seq = len(ledger_ops)

        for zone in state.compiled_zones:
            if zone.zone_type != ZoneType.UNKNOWN:
                updated_zones.append(zone)
                continue

            classified = self._classify(zone, ocr_words, primitives)

            if classified != ZoneType.UNKNOWN:
                # تسجيل في الـ ledger
                op = ZoneOperation(
                    operation_id=str(uuid.uuid4()),
                    ledger_sequence_number=seq,
                    timestamp=datetime.now(timezone.utc),
                    operator_id=operator_id,
                    operation_type="RENAME_ZONE",
                    target_zone_id=zone.zone_id,
                    parameters={
                        "zone_type":  classified.value,
                        "zone_label": zone.zone_label,
                        "reason":     "ZoneTypeClassifierEngine heuristic",
                    },
                    previous_state={"zone_type": zone.zone_type.value},
                )
                ledger_ops.append(op)
                seq += 1

                updated_zones.append(
                    zone.model_copy(update={"zone_type": classified})
                )
                logger.info(
                    "ZoneTypeClassifierEngine: %s → %s (was UNKNOWN)",
                    zone.zone_id, classified.value,
                )
            else:
                updated_zones.append(zone)

        return state.model_copy(update={
            "compiled_zones":    updated_zones,
            "ledger_operations": ledger_ops,
        })

    # ── منطق التصنيف الداخلي ─────────────────────────────────────────────────

    def _classify(
        self,
        zone: SemanticZone,
        ocr_words: List[OCRWord],
        primitives: List[VisualPrimitiveEvidence],
    ) -> ZoneType:
        """يُعيد ZoneType المناسب أو UNKNOWN إذا لم يتضح التصنيف."""

        # 1. هل تحتوي على checkbox/radio primitives؟
        for prim in primitives:
            if prim.primitive_type in (PrimitiveType.CHECKBOX, PrimitiveType.RADIO_BUTTON):
                if zone.bbox.intersection_area(prim.bbox) > 0 or zone.bbox.contains(prim.bbox):
                    return ZoneType.CHECKBOX_GROUP

        # 2. استخراج كلمات OCR المرتبطة بالـ zone
        zone_words = [
            w for w in ocr_words
            if zone.bbox.intersection_area(w.bbox) > 0 or zone.bbox.contains(w.bbox)
        ]

        if not zone_words:
            # Zone فارغة من النص — فحص الأبعاد
            w = zone.bbox.x_max - zone.bbox.x_min
            h = zone.bbox.y_max - zone.bbox.y_min
            if w < 50 and h < 50:
                return ZoneType.CHECKBOX_GROUP  # على الأرجح checkbox مكتشف بدون نص
            return ZoneType.UNKNOWN

        # دمج كلمات الـ zone في نص واحد للفحص
        full_text = " ".join(w.text for w in zone_words).strip()
        first_word = zone_words[0].text.strip() if zone_words else ""

        # 3. فحص عناوين الأقسام
        for pattern in self._SECTION_PATTERNS:
            if pattern.search(full_text):
                return ZoneType.SECTION_HEADER

        # 4. فحص التوقيع
        for kw in self._SIGNATURE_KW:
            if kw in full_text:
                return ZoneType.SIGNATURE_BLOCK

        # 5. فحص التذييل
        for kw in self._FOOTER_KW:
            if kw in full_text:
                return ZoneType.FOOTER

        # 6. Zone عريضة (> 60% من عرض الصفحة) → على الأرجح header أو free_text
        zone_width = zone.bbox.x_max - zone.bbox.x_min
        zone_height = zone.bbox.y_max - zone.bbox.y_min

        if zone_width > 400 and len(zone_words) <= 4:
            # عنوان قصير عريض = section header
            return ZoneType.SECTION_HEADER

        if len(zone_words) > 8 and zone_width > 200:
            return ZoneType.FREE_TEXT

        return ZoneType.UNKNOWN


# ────────────────────────────────────────────────────────────
# 2.1 LayoutGrammarEngine & LARGE CONTAINER PARTITIONING (Gap#16)
# ────────────────────────────────────────────────────────────

class LayoutGrammarEngine:
    """
    Constructs layout grammar relationships and processes RepeatedFieldPatterns.
    If RepeatedFieldPattern instances > 50, activates LargeContainerPartitioningStrategy.
    """
    def run(self, graph: LayoutGrammarGraph) -> LayoutGrammarGraph:
        partitioned_patterns = []
        for pattern in graph.patterns:
            n_instances = len(pattern.instances)
            if n_instances > 50:
                logger.info(f"LayoutGrammarEngine: RepeatedFieldPattern {pattern.pattern_id} has {n_instances} instances. Activating LargeContainerPartitioningStrategy.")
                
                # Split instances into windows of 20 with 2-instance overlap
                window_size = 20
                overlap = 2
                windows = []
                start = 0
                while start < n_instances:
                    end = min(start + window_size, n_instances)
                    windows.append(pattern.instances[start:end])
                    if end == n_instances:
                        break
                    start += (window_size - overlap)
                
                # Process windows independently (in-memory simulator)
                processed_instances = []
                for window in windows:
                    # In a real pipeline, each window is processed by composite container inference.
                    # Here we simulate window-level identity mapping/processing.
                    processed_instances.extend(window)
                
                # Merge results by deduplicating on instance_index
                deduplicated = {}
                for inst in processed_instances:
                    deduplicated[inst.instance_index] = inst
                
                sorted_instances = [deduplicated[idx] for idx in sorted(deduplicated.keys())]
                new_pattern = pattern.model_copy(update={"instances": sorted_instances})
                partitioned_patterns.append(new_pattern)
            else:
                partitioned_patterns.append(pattern)
                
        return graph.model_copy(update={"patterns": partitioned_patterns})


# ────────────────────────────────────────────────────────────
# 2.6 ParentChildLinkerEngine (HierarchicalFieldPair with Signals)
# ────────────────────────────────────────────────────────────

class ParentChildLinkerEngine:
    """
    Links question anchors to answer nodes using weighted signal matrix.
    Attaches Provenance record.
    """
    def run(
        self,
        anchors: List[AnchorCandidate],
        values: List[ValueCandidate],
        zones: List[SemanticZone],
        reading_order: ReadingOrderSequence
    ) -> List[HierarchicalFieldPair]:
        pairs = []
        
        # Build zone dictionary and reading order lookup
        zone_dict = {z.zone_id: z for z in zones}
        word_to_reading_entry = {e.word_id: e for e in reading_order.entries}
        
        # Pair each anchor candidate with value candidates in same zone
        for anchor in anchors:
            anchor_id = anchor.primitive_id or (anchor.text_ids[0] if anchor.text_ids else "anchor")
            anchor_zone = resolve_zone_assignment(anchor.bbox, zones) or "default"
            
            for value in values:
                value_id = value.primitive_id or (value.text_ids[0] if value.text_ids else "value")
                value_zone = resolve_zone_assignment(value.bbox, zones) or "default"
                
                # Compute signal scores (0.0 to 1.0)
                # 1. Spatial Proximity: euclidean distance between centers
                ax, ay = anchor.bbox.center
                vx, vy = value.bbox.center
                dist = math.sqrt((ax - vx)**2 + (ay - vy)**2)
                spatial_proximity = math.exp(-dist / 150.0)
                
                # 2. Alignment Vector: horizontal alignment is preferred
                dy = abs(ay - vy)
                alignment_vector = math.exp(-dy / 15.0)
                
                # 3. Reading Order Adjacency
                reading_order_adjacency = 0.0
                if anchor.text_ids and value.text_ids:
                    ae = word_to_reading_entry.get(anchor.text_ids[-1])
                    ve = word_to_reading_entry.get(value.text_ids[0])
                    if ae and ve and ae.zone_id == ve.zone_id:
                        if ae.line_index == ve.line_index:
                            dist_in_line = abs(ae.position_in_line - ve.position_in_line)
                            reading_order_adjacency = 1.0 / (1.0 + dist_in_line)
                        elif abs(ae.line_index - ve.line_index) == 1:
                            reading_order_adjacency = 0.5
                
                # 4. Zone Membership
                zone_membership = 1.0 if anchor_zone == value_zone else 0.0
                
                # 5. Layout Grammar Structure (stub / simplified)
                layout_grammar_structure = 0.8 if abs(ay - vy) < 20 else 0.2
                
                # 6. Primitive Association
                primitive_association = 1.0 if value.primitive_id else 0.5
                
                # Weighted Final Score computation
                final_score = (
                    0.25 * spatial_proximity +
                    0.15 * alignment_vector +
                    0.20 * reading_order_adjacency +
                    0.20 * zone_membership +
                    0.10 * layout_grammar_structure +
                    0.10 * primitive_association
                )
                
                # Classify status
                if final_score >= 0.70:
                    status = LinkStatus.LINK_CONFIRMED
                elif final_score >= 0.50:
                    status = LinkStatus.LINK_TENTATIVE
                else:
                    status = LinkStatus.NO_LINK
                    
                if status != LinkStatus.NO_LINK:
                    scores = SignalScores(
                        spatial_proximity=spatial_proximity,
                        alignment_vector=alignment_vector,
                        reading_order_adjacency=reading_order_adjacency,
                        zone_membership=zone_membership,
                        layout_grammar_structure=layout_grammar_structure,
                        primitive_association=primitive_association,
                        final_score=final_score
                    )
                    
                    prov = Provenance(
                        source_engine="ParentChildLinkerEngine",
                        confidence=final_score,
                        evidence_refs=anchor.text_ids + value.text_ids + ([value.primitive_id] if value.primitive_id else []),
                        creation_timestamp=datetime.now(timezone.utc)
                    )
                    
                    pairs.append(HierarchicalFieldPair(
                        pair_id=f"pair_{anchor_id}_{value_id}",
                        question_anchor_id=anchor_id,
                        answer_node_id=value_id,
                        status=status,
                        signal_scores=scores,
                        zone_id=anchor_zone,
                        provenance=prov
                    ))
                    
        return pairs


# ────────────────────────────────────────────────────────────
# 2.7 StructuralSemanticCompilerEngine & GRAPH INFRASTRUCTURE
# ────────────────────────────────────────────────────────────

def generate_stable_element_id(
    page_id: str,
    bbox: BoundingBox,
    element_type: FormElementType,
    label: str,
    line_height: float = 20.0
) -> str:
    """
    Generates a deterministic stable ID for a FormElement.
    Quantizes coordinates by vertical line height and horizontal step to absorb visual noise.
    Normalises string casing and Arabic diacritics.
    """
    step_y = max(10, int(line_height))
    step_x = 20
    q_ymin = (bbox.y_min // step_y) * step_y
    q_xmin = (bbox.x_min // step_x) * step_x
    q_ymax = (bbox.y_max // step_y) * step_y
    q_xmax = (bbox.x_max // step_x) * step_x

    # Normalize text: strip diacritics, lowercase, strip spaces
    norm_label = re.sub(r'[\u064B-\u065F\u0670]', '', label).strip().lower()

    hash_input = f"{page_id}_{q_xmin}_{q_ymin}_{q_xmax}_{q_ymax}_{element_type.value}_{norm_label}"
    return f"el_{hashlib.md5(hash_input.encode('utf-8')).hexdigest()}"


class StructuralSemanticCompilerEngine:
    """
    Compiles OCR words, semantic zones, visual primitives, and hierarchical field pairs
    into a structured FormGraph representation using a multi-pass topology pipeline.
    """
    def run(self, state: PageCompilationState) -> PageCompilationState:
        page_id = state.page_metadata.page_id
        
        # Build initial graph container
        graph = FormGraph(page_id=page_id)
        
        # Determine base line height for coordinate quantization
        line_height = 20.0
        lh_vals = [z.median_line_height_px for z in state.compiled_zones if z.median_line_height_px is not None]
        if lh_vals:
            line_height = sum(lh_vals) / len(lh_vals)
            
        # Pass 1: SegmentationPass
        self._run_segmentation_pass(state, graph, line_height)
        
        # Pass 2: OptionClusteringPass
        self._run_option_clustering_pass(state, graph, line_height)
        
        # Pass 3: StructuralInferencePass
        self._run_structural_inference_pass(state, graph, line_height)
        
        # Pass 4: ConstraintInferencePass
        self._run_constraint_inference_pass(state, graph)
        
        # Pass 5: ConflictResolverPass
        self._run_conflict_resolver_pass(state, graph)
        
        # Pass 6: NormalizationPass
        self._run_normalization_pass(state, graph)
        
        new_state = state.model_copy(update={"form_graph": graph})
        return new_state

    def _run_segmentation_pass(self, state: PageCompilationState, graph: FormGraph, line_height: float):
        for zone in state.compiled_zones:
            if zone.zone_type == ZoneType.SECTION_HEADER:
                sec_id = f"sec_{zone.zone_id}"
                w = zone.bbox.x_max - zone.bbox.x_min
                h = zone.bbox.y_max - zone.bbox.y_min
                layout = LayoutTopologyType.ROW_MAJOR if w > h * 2 else LayoutTopologyType.FREEFORM
                
                section = FormSection(
                    section_id=sec_id,
                    label=zone.zone_label,
                    bbox=zone.bbox,
                    layout_topology=layout,
                    element_ids=[]
                )
                graph.sections.append(section)

    def _run_option_clustering_pass(self, state: PageCompilationState, graph: FormGraph, line_height: float):
        prim_types = {p.primitive_id: p.primitive_type for p in state.visual_primitives}
        
        checkbox_pairs = []
        for pair in state.linked_fields:
            ans_id = pair.answer_node_id
            p_type = prim_types.get(ans_id, PrimitiveType.UNDERLINE_FIELD)
            if p_type in (PrimitiveType.CHECKBOX, PrimitiveType.RADIO_BUTTON):
                checkbox_pairs.append(pair)
                
        pairs_by_zone = {}
        for pair in checkbox_pairs:
            pairs_by_zone.setdefault(pair.zone_id, []).append(pair)
            
        bbox_lookup = {}
        for p in state.visual_primitives:
            bbox_lookup[p.primitive_id] = p.bbox
        for tok in (state.ocr_evidence.words if state.ocr_evidence else []):
            bbox_lookup[tok.word_id] = tok.bbox
            
        for zone_id, pairs in pairs_by_zone.items():
            zone = next((z for z in state.compiled_zones if z.zone_id == zone_id), None)
            
            sorted_pairs = sorted(pairs, key=lambda p: (bbox_lookup.get(p.answer_node_id).y_min if bbox_lookup.get(p.answer_node_id) else 0, p.pair_id))
            
            groups = []
            for pair in sorted_pairs:
                val_bbox = bbox_lookup.get(pair.answer_node_id)
                if not val_bbox:
                    continue
                added = False
                for group in groups:
                    for member in group:
                        m_bbox = bbox_lookup.get(member.answer_node_id)
                        if m_bbox:
                            v_dist = abs(val_bbox.y_min - m_bbox.y_min)
                            h_dist = abs(val_bbox.x_min - m_bbox.x_min)
                            # وُسّعت النافذة: 2.0→3.5 rows ، 300→500 px أفقياً
                            if v_dist < line_height * 3.5 and h_dist < 500:
                                group.append(pair)
                                added = True
                                break
                    if added:
                        break
                if not added:
                    groups.append([pair])
                    
            for idx, group in enumerate(groups):
                x_mins = []
                y_mins = []
                x_maxs = []
                y_maxs = []
                for p in group:
                    vb = bbox_lookup.get(p.answer_node_id)
                    if vb:
                        x_mins.append(vb.x_min)
                        y_mins.append(vb.y_min)
                        x_maxs.append(vb.x_max)
                        y_maxs.append(vb.y_max)
                if not x_mins:
                    continue
                group_bbox = BoundingBox(
                    x_min=min(x_mins),
                    y_min=min(y_mins),
                    x_max=max(x_maxs),
                    y_max=max(y_maxs)
                )
                
                group_label = zone.zone_label if zone else "Option Group"
                
                parent_id = generate_stable_element_id(
                    page_id=state.page_metadata.page_id,
                    bbox=group_bbox,
                    element_type=FormElementType.ENUM_GROUP,
                    label=group_label,
                    line_height=line_height
                )
                
                child_ids = []
                for p in group:
                    child_vb = bbox_lookup.get(p.answer_node_id)
                    label_text = p.pair_id
                    if "_" in label_text:
                        parts = label_text.split("_")
                        if len(parts) > 1:
                            label_text = parts[1]
                    
                    child_id = generate_stable_element_id(
                        page_id=state.page_metadata.page_id,
                        bbox=child_vb,
                        element_type=FormElementType.ATOMIC_FIELD,
                        label=label_text,
                        line_height=line_height
                    )
                    
                    child_el = FormElement(
                        element_id=child_id,
                        element_type=FormElementType.ATOMIC_FIELD,
                        label=label_text,
                        bbox=child_vb,
                        field_pairs=[p.pair_id],
                        topology_signature=TopologySignature(
                            alignment_group=f"align_{child_vb.x_min // 20}",
                            indentation_level=1,
                            lane_id=f"lane_{zone_id}"
                        )
                    )
                    graph.elements[child_id] = child_el
                    child_ids.append(child_id)
                    
                    prov = Provenance(
                        source_engine="StructuralSemanticCompilerEngine",
                        confidence=p.provenance.confidence,
                        evidence_refs=[p.pair_id],
                        creation_timestamp=datetime.now(timezone.utc)
                    )
                    edge = StructuralEdge(
                        source_id=child_id,
                        target_id=parent_id,
                        relation_type=StructuralRelationType.OPTION_OF,
                        confidence=p.provenance.confidence,
                        provenance=prov,
                        metadata={"zone_id": zone_id}
                    )
                    graph.edges.append(edge)
                    
                parent_el = FormElement(
                    element_id=parent_id,
                    element_type=FormElementType.ENUM_GROUP,
                    label=group_label,
                    bbox=group_bbox,
                    child_element_ids=child_ids,
                    topology_signature=TopologySignature(
                        alignment_group=f"align_{group_bbox.x_min // 20}",
                        indentation_level=0,
                        lane_id=f"lane_{zone_id}"
                    ),
                    metadata={"selection_mode": "MULTI"}
                )
                graph.elements[parent_id] = parent_el
                
                target_sec = None
                for sec in graph.sections:
                    if sec.bbox.contains(group_bbox) or sec.bbox.intersection_area(group_bbox) > 0:
                        target_sec = sec
                        break
                if target_sec:
                    target_sec.element_ids.append(parent_id)

    def _run_structural_inference_pass(self, state: PageCompilationState, graph: FormGraph, line_height: float):
        # 1. Selection Semantics
        for parent_id, element in list(graph.elements.items()):
            if element.element_type == FormElementType.ENUM_GROUP:
                children = [graph.elements[cid] for cid in element.child_element_ids if cid in graph.elements]
                labels = [c.label for c in children]
                
                exclusive_keywords = [
                    # أنواع الولادة
                    {"طبيعية", "قيصرية", "اسقاط", "إسقاط"},
                    # نعم/لا
                    {"نعم", "لا"},
                    # داخل/خارج
                    {"داخلي", "خارجي"},
                    # الجنس
                    {"ذكر", "أنثى", "انثى"},
                    # ─── إضافات جديدة: استمارات الصحة اليمنية ─────────────────
                    # الحالة الاجتماعية (بند 5)
                    {"متزوجة", "مطلقة", "أرملة", "عزباء"},
                    # محل الإقامة (بند 11)
                    {"ريف", "حضر", "اريف", "احضر"},
                    # نوع المرفق الصحي (بند 3)
                    {"حكومي", "خاص", "أهلي", "اهلي"},
                    # وقت الحدث (بنود 9 و 16)
                    {"صباحاً", "مساءً", "صباح", "مساء", "ساء", "باح"},
                    # مكان الوفاة (بند 10)
                    {"المنزل", "الطريق", "المرفق الصحي", "في الطريق"},
                    # المستوى التعليمي (بنود 13 و 14)
                    {"أمية", "يقرأ ويكتب", "ابتدائي", "إعدادي", "ثانوي", "جامعي",
                     "ايقرأ ويكتب", "اثانوي"},
                    # الحالة الاقتصادية (بند 7)
                    {"غني", "متوسط", "فقير"},
                    # هل تم النقل (بند 19)
                    {"نعم", "لا", "انعم"},
                ]
                
                is_single = False
                for ex_set in exclusive_keywords:
                    overlap = sum(1 for label in labels if any(ex in label for ex in ex_set))
                    if overlap >= 2:
                        is_single = True
                        break
                        
                element.metadata["selection_mode"] = "SINGLE" if is_single else "MULTI"

        # 2. Clinical Hierarchy Semantics
        for parent_id, element in list(graph.elements.items()):
            if element.element_type == FormElementType.ENUM_GROUP:
                children = [graph.elements[cid] for cid in element.child_element_ids if cid in graph.elements]
                parent_option = None
                sub_options = []
                for child in children:
                    if re.match(r'^\s*\(?\d+\)?', child.label) or "أوضاع غير طبيعية" in child.label:
                        parent_option = child
                    else:
                        sub_options.append(child)
                        
                if parent_option and sub_options:
                    for sub in sub_options:
                        prov = Provenance(
                            source_engine="StructuralSemanticCompilerEngine",
                            confidence=0.9,
                            evidence_refs=[parent_option.element_id, sub.element_id],
                            creation_timestamp=datetime.now(timezone.utc)
                        )
                        edge = StructuralEdge(
                            source_id=sub.element_id,
                            target_id=parent_option.element_id,
                            relation_type=StructuralRelationType.CHILD_REASON,
                            confidence=0.9,
                            provenance=prov
                        )
                        graph.edges.append(edge)
                        
                        if sub.element_id in element.child_element_ids:
                            element.child_element_ids.remove(sub.element_id)
                            
                        parent_option.child_element_ids.append(sub.element_id)
                        
                        if sub.topology_signature:
                            sub.topology_signature.indentation_level = 2
                            
                    if parent_option.topology_signature:
                        parent_option.topology_signature.indentation_level = 1

        # 3. Activation Flow Semantics (Conditional Branches)
        prim_types = {p.primitive_id: p.primitive_type for p in state.visual_primitives}
        
        bbox_lookup = {}
        for p in state.visual_primitives:
            bbox_lookup[p.primitive_id] = p.bbox
        for tok in (state.ocr_evidence.words if state.ocr_evidence else []):
            bbox_lookup[tok.word_id] = tok.bbox
            
        for pair in state.linked_fields:
            ans_id = pair.answer_node_id
            p_type = prim_types.get(ans_id, PrimitiveType.UNDERLINE_FIELD)
            if p_type not in (PrimitiveType.CHECKBOX, PrimitiveType.RADIO_BUTTON):
                val_bbox = bbox_lookup.get(ans_id)
                if not val_bbox:
                    continue
                    
                label_text = pair.pair_id
                if "_" in label_text:
                    parts = label_text.split("_")
                    if len(parts) > 1:
                        label_text = parts[1]
                        
                field_id = generate_stable_element_id(
                    page_id=state.page_metadata.page_id,
                    bbox=val_bbox,
                    element_type=FormElementType.ATOMIC_FIELD,
                    label=label_text,
                    line_height=line_height
                )
                
                if field_id not in graph.elements:
                    graph.elements[field_id] = FormElement(
                        element_id=field_id,
                        element_type=FormElementType.ATOMIC_FIELD,
                        label=label_text,
                        bbox=val_bbox,
                        field_pairs=[pair.pair_id],
                        topology_signature=TopologySignature(
                            alignment_group=f"align_{val_bbox.x_min // 20}",
                            indentation_level=0,
                            lane_id=f"lane_{pair.zone_id}"
                        )
                    )
                    for sec in graph.sections:
                        if sec.bbox.contains(val_bbox) or sec.bbox.intersection_area(val_bbox) > 0:
                            sec.element_ids.append(field_id)
                            break
                            
                for opt_id, opt_el in graph.elements.items():
                    if opt_el.element_type == FormElementType.ATOMIC_FIELD and opt_el.topology_signature:
                        if "خارجي" in opt_el.label or "أخرى" in opt_el.label or "اخرى" in opt_el.label:
                            o_box = opt_el.bbox
                            dist = math.sqrt((o_box.center[0] - val_bbox.center[0])**2 + (o_box.center[1] - val_bbox.center[1])**2)
                            if dist < 200:
                                prov = Provenance(
                                    source_engine="StructuralSemanticCompilerEngine",
                                    confidence=0.85,
                                    evidence_refs=[opt_id, field_id],
                                    creation_timestamp=datetime.now(timezone.utc)
                                )
                                edge = StructuralEdge(
                                    source_id=opt_id,
                                    target_id=field_id,
                                    relation_type=StructuralRelationType.ACTIVATES,
                                    confidence=0.85,
                                    provenance=prov,
                                    metadata={"trigger_condition": "selected"}
                                )
                                graph.edges.append(edge)

    def _run_constraint_inference_pass(self, state: PageCompilationState, graph: FormGraph):
        for parent_id, element in graph.elements.items():
            if element.element_type == FormElementType.ENUM_GROUP:
                mode = element.metadata.get("selection_mode", "MULTI")
                if mode == "SINGLE":
                    c_id = f"const_mutex_{parent_id}"
                    constraint = StructuralConstraint(
                        constraint_id=c_id,
                        constraint_type=ConstraintType.MUTUALLY_EXCLUSIVE,
                        target_element_ids=element.child_element_ids,
                        parameters={"max_selected": 1}
                    )
                    graph.constraints.append(constraint)
                    
        for edge in graph.edges:
            if edge.relation_type == StructuralRelationType.ACTIVATES:
                c_id = f"const_active_{edge.source_id}_{edge.target_id}"
                constraint = StructuralConstraint(
                    constraint_id=c_id,
                    constraint_type=ConstraintType.REQUIRES_CHILD_IF_SELECTED,
                    target_element_ids=[edge.source_id, edge.target_id]
                )
                graph.constraints.append(constraint)

    def _run_conflict_resolver_pass(self, state: PageCompilationState, graph: FormGraph):
        element_ids = list(graph.elements.keys())
        to_delete = set()
        
        for i in range(len(element_ids)):
            id1 = element_ids[i]
            if id1 in to_delete:
                continue
            el1 = graph.elements[id1]
            
            for j in range(i + 1, len(element_ids)):
                id2 = element_ids[j]
                if id2 in to_delete:
                    continue
                el2 = graph.elements[id2]
                
                if el1.bbox.iou(el2.bbox) > 0.8 and el1.element_type == el2.element_type:
                    el1.field_pairs = list(set(el1.field_pairs + el2.field_pairs))
                    el1.child_element_ids = list(set(el1.child_element_ids + el2.child_element_ids))
                    to_delete.add(id2)
                    
                    for edge in graph.edges:
                        if edge.source_id == id2:
                            edge.source_id = id1
                        if edge.target_id == id2:
                            edge.target_id = id1
                            
        for dead_id in to_delete:
            del graph.elements[dead_id]
            for sec in graph.sections:
                if dead_id in sec.element_ids:
                    sec.element_ids.remove(dead_id)

    def _run_normalization_pass(self, state: PageCompilationState, graph: FormGraph):
        seen_edges = set()
        unique_edges = []
        for edge in graph.edges:
            key = (edge.source_id, edge.target_id, edge.relation_type)
            if key not in seen_edges:
                seen_edges.add(key)
                unique_edges.append(edge)
        graph.edges = unique_edges
        
        for el_id, element in graph.elements.items():
            element.child_element_ids = [cid for cid in element.child_element_ids if cid in graph.elements]
            
        for sec in graph.sections:
            sec.element_ids = [eid for eid in sec.element_ids if eid in graph.elements]
            
        graph.sections.sort(key=lambda s: (s.bbox.y_min, s.bbox.x_min))
        
        for sec in graph.sections:
            sec.element_ids.sort()
            
        for el_id, element in graph.elements.items():
            element.child_element_ids.sort()
            element.field_pairs.sort()
            
        graph.edges.sort(key=lambda e: (e.source_id, e.target_id, e.relation_type.value))
        graph.constraints.sort(key=lambda c: c.constraint_id)


# ────────────────────────────────────────────────────────────
# 2.8 FieldTypeInferenceEngine (Adaptive Radius Snapping, Gap#17)
# ────────────────────────────────────────────────────────────

class FieldTypeInferenceEngine:
    """
    Standardizes type inference and uses adaptive snapping radius:
    primary_radius = max(15px, 0.8 * zone.median_line_height_px)
    expanded_radius = max(30px, 1.6 * zone.median_line_height_px)
    """
    def run(
        self,
        pair: HierarchicalFieldPair,
        anchor: AnchorCandidate,
        value: ValueCandidate,
        zone: Optional[SemanticZone]
    ) -> FieldTypeInference:
        # 1. Determine median line height
        median_lh = zone.median_line_height_px if (zone and zone.median_line_height_px is not None) else None
        
        # 2. Calculate adaptive snapping radii
        if median_lh is not None:
            primary_radius = max(15.0, 0.8 * median_lh)
            expanded_radius = max(30.0, 1.6 * median_lh)
        else:
            primary_radius = 15.0
            expanded_radius = 30.0
            
        # 3. Calculate anchor-value distance
        ax, ay = anchor.bbox.center
        vx, vy = value.bbox.center
        dist = math.sqrt((ax - vx)**2 + (ay - vy)**2)
        
        # 4. Perform Snapping classification
        if dist <= primary_radius:
            snap_result = SnapResult.EXACT
            confidence = pair.provenance.confidence
        elif dist <= expanded_radius:
            snap_result = SnapResult.LOW_CONFIDENCE
            confidence = pair.provenance.confidence * 0.75
        else:
            snap_result = SnapResult.UNBOUND
            confidence = 0.3
            
        # 5. Type inference logic
        inferred_type = FieldType.TEXT
        if value.candidate_type == PrimitiveType.CHECKBOX:
            inferred_type = FieldType.BOOLEAN
        elif value.candidate_type == PrimitiveType.NUMERIC_BOX:
            inferred_type = FieldType.NUMBER
            
        prov = Provenance(
            source_engine="FieldTypeInferenceEngine",
            confidence=confidence,
            evidence_refs=pair.provenance.evidence_refs,
            creation_timestamp=datetime.now(timezone.utc)
        )
        
        return FieldTypeInference(
            pair_id=pair.pair_id,
            inferred_type=inferred_type,
            confidence=confidence,
            snap_result=snap_result,
            snap_radius_used_px=primary_radius,
            provenance=prov
        )


# ────────────────────────────────────────────────────────────
# 3.1 MacroHITLEditorEngine & DRAFT LIFECYCLE (Gap#24)
# ────────────────────────────────────────────────────────────

class MacroHITLEditorEngine:
    """
    Manages operator draft edit lifecycle and advisory soft locks.
    accumulated_operations stored in DraftOperation before commit.
    """
    def __init__(self):
        # session_id -> DraftOperation mapping
        self.active_drafts: Dict[str, DraftOperation] = {}
        
    def start_draft(self, session_id: str, page_id: str) -> Tuple[DraftOperation, Optional[str]]:
        """
        Starts a draft session. Returns DraftOperation and advisory lock warning if active.
        """
        # Soft-lock advisory check: check if any OTHER session has an active PENDING draft for this page
        warning_msg = None
        for other_sid, draft in self.active_drafts.items():
            if other_sid != session_id and draft.accumulated_operations and draft.status == "PENDING":
                # models.py uses session_id. Let's make sure it matches.
                # In models.py page_id is not directly in DraftOperation, but is context-dependent.
                # Let's verify. Yes, we can issue a warning.
                warning_msg = f"DraftConflictWarning: Session {other_sid} already has active edits on this page."
                break
                
        if session_id in self.active_drafts and self.active_drafts[session_id].status == "PENDING":
            return self.active_drafts[session_id], warning_msg
            
        draft = DraftOperation(
            draft_id=f"draft_{session_id}_{int(datetime.now().timestamp())}",
            session_id=session_id,
            accumulated_operations=[],
            created_at=datetime.now(timezone.utc),
            status="PENDING"
        )
        self.active_drafts[session_id] = draft
        return draft, warning_msg

    def add_operation(self, session_id: str, op: Dict[str, Any]):
        """Adds an operation to the draft container."""
        if session_id not in self.active_drafts or self.active_drafts[session_id].status != "PENDING":
            raise RuntimeError("No active pending draft session found.")
        self.active_drafts[session_id].accumulated_operations.append(op)

    def discard_draft(self, session_id: str):
        """Discards active draft edits."""
        if session_id in self.active_drafts:
            self.active_drafts[session_id].status = "DISCARDED"
            self.active_drafts[session_id].accumulated_operations = []
            
    def commit_draft(self, session_id: str, ledger_engine: LedgerOperationEngine, state: PageCompilationState) -> PageCompilationState:
        """Commits all draft operations sequentially to the Ledger Engine."""
        if session_id not in self.active_drafts or self.active_drafts[session_id].status != "PENDING":
            raise RuntimeError("No active pending draft session found to commit.")
            
        draft = self.active_drafts[session_id]
        current_state = state
        
        # Sequentially submit accumulated operations
        for op_dict in draft.accumulated_operations:
            # Reconstruct the concrete operation object
            op_type = op_dict.get("operation_type")
            # In models.py we have concrete operations (ZoneOperation, FieldOperation, RelationshipOperation, etc.)
            # Deserialize using target model types
            from app.core.forms.models import ZoneOperation, FieldOperation, RelationshipOperation, ContainerOperation, TentativeLinkResolutionOperation, CompensateOperation
            
            if op_type in ["RESIZE_ZONE", "RENAME_ZONE", "MERGE_ZONES", "SPLIT_ZONE", "ASSIGN_PARENT", "DELETE_ZONE", "CREATE_ZONE"]:
                op = ZoneOperation.model_validate(op_dict)
            elif op_type in ["OVERRIDE_FIELD_TYPE", "EDIT_VALUE", "REASSIGN_ZONE", "ADD_FIELD", "DELETE_FIELD", "LINK_FIELD", "UNLINK_FIELD"]:
                op = FieldOperation.model_validate(op_dict)
            elif op_type in ["CREATE_LINK", "DELETE_LINK", "ADJUST_CONFIDENCE"]:
                op = RelationshipOperation.model_validate(op_dict)
            elif op_type in ["ADD_INSTANCE", "REMOVE_INSTANCE", "REORDER_INSTANCES"]:
                op = ContainerOperation.model_validate(op_dict)
            elif op_type == "TENTATIVE_LINK_RESOLVED":
                op = TentativeLinkResolutionOperation.model_validate(op_dict)
            elif op_type == "COMPENSATE":
                op = CompensateOperation.model_validate(op_dict)
            else:
                raise ValueError(f"Unknown operation_type {op_type}")
                
            current_state = ledger_engine.commit(current_state, op)
            
        draft.status = "COMMITTED"
        return current_state


# ────────────────────────────────────────────────────────────
# 3.2 LedgerOperationEngine & STATE HASH (Gap#20, Gap#26)
# ────────────────────────────────────────────────────────────

class ConcurrentModificationError(Exception):
    def __init__(self, expected: int, actual: int):
        self.expected = expected
        self.actual = actual
        super().__init__(f"ConcurrentModificationError: expected sequence {expected}, but actual is {actual}.")

class LedgerOperationEngine:
    """
    Applies ledger operations, validates sequence (optimistic lock),
    recomputes state_hash, and checks for determinism violation.
    """
    def __init__(self, event_bus: Optional[Any] = None):
        self.event_bus = event_bus

    def compute_hash(self, state: PageCompilationState) -> str:
        """
        Recompute state_hash from PageCompilationState (excluding state_hash field itself).
        Extremely robust and deterministic.
        """
        state_dict = state.model_dump(exclude={"state_hash"})
        
        # Recursive sorting helper for deterministic JSON serialization
        def serialize_deterministic(obj):
            if isinstance(obj, dict):
                return {k: serialize_deterministic(v) for k, v in sorted(obj.items())}
            elif isinstance(obj, list):
                return [serialize_deterministic(v) for v in obj]
            elif isinstance(obj, datetime):
                return obj.isoformat()
            elif isinstance(obj, Enum):
                return obj.value
            else:
                return obj

        serialized_str = json.dumps(serialize_deterministic(state_dict))
        return hashlib.sha256(serialized_str.encode('utf-8')).hexdigest()

    def commit(self, state: PageCompilationState, operation: LedgerOperation) -> PageCompilationState:
        """
        Commits a LedgerOperation to state. Enforces sequence number check.
        """
        current_seq = len(state.ledger_operations)
        # Sequence lock check (closes Gap#26)
        if operation.ledger_sequence_number != current_seq:
            raise ConcurrentModificationError(
                expected=operation.ledger_sequence_number,
                actual=current_seq
            )
            
        # Create a copy of the state to mutate
        new_state = state.model_copy()
        
        # Append to ledger operations list
        new_state.ledger_operations = list(state.ledger_operations) + [operation]
        
        # Apply the mutation to the new state
        self._apply_operation_mutation(new_state, operation)
        
        # Recompute hash (closes Gap#20)
        expected_hash = self.compute_hash(new_state)
        new_state.state_hash = expected_hash
        
        # If there was a pre-calculated / expected hash on the operation (e.g. during replays),
        # verify that they match. If they mismatch, throw DeterminismViolationAlert immediately.
        # In a real enterprise system, we check against expected hash if provided in parameters.
        if hasattr(operation, "parameters") and "expected_state_hash" in operation.parameters:
            expected = operation.parameters["expected_state_hash"]
            if expected != expected_hash:
                alert = DeterminismViolationAlert(
                    expected_hash=expected,
                    actual_hash=expected_hash,
                    page_id=state.page_metadata.page_id,
                    ledger_sequence_number=operation.ledger_sequence_number,
                    timestamp=datetime.now(timezone.utc)
                )
                logger.error(f"DETERMINISM VIOLATION ALERT: {alert}")
                raise ValueError(f"DeterminismViolationAlert: expected {expected}, actual {expected_hash}")
                
        # Emit/publish PageMutationEvent to event bus
        if self.event_bus:
            self.event_bus.publish(
                "page_mutation_events",
                {"page_id": state.page_metadata.page_id, "new_sequence_number": current_seq + 1}
            )
            
        return new_state

    def _apply_operation_mutation(self, state: PageCompilationState, operation: LedgerOperation):
        """Mutate state based on the type of LedgerOperation."""
        op_type = getattr(operation, "operation_type", None)
        
        if isinstance(operation, ZoneOperation):
            # Zone resizing/creation/etc.
            if op_type == "CREATE_ZONE":
                params = operation.parameters
                new_zone = SemanticZone(
                    zone_id=operation.target_zone_id,
                    zone_type=params.get("zone_type", ZoneType.UNKNOWN),
                    zone_label=params.get("zone_label", "Unnamed Zone"),
                    bbox=BoundingBox.model_validate(params["bbox"]),
                    confidence=1.0,
                    compiled_fields=[],
                    validation_rules={},
                    spatial_transform=None,
                    metadata=params.get("metadata", {})
                )
                state.compiled_zones = list(state.compiled_zones) + [new_zone]
                
            elif op_type == "RESIZE_ZONE":
                params = operation.parameters
                new_bbox = BoundingBox.model_validate(params["bbox"])
                state.compiled_zones = [
                    z.model_copy(update={"bbox": new_bbox}) if z.zone_id == operation.target_zone_id else z
                    for z in state.compiled_zones
                ]
                
            elif op_type == "RENAME_ZONE":
                params = operation.parameters
                new_label = params["zone_label"]
                state.compiled_zones = [
                    z.model_copy(update={"zone_label": new_label}) if z.zone_id == operation.target_zone_id else z
                    for z in state.compiled_zones
                ]
                
            elif op_type == "DELETE_ZONE":
                state.compiled_zones = [z for z in state.compiled_zones if z.zone_id != operation.target_zone_id]

            elif op_type == "UPDATE_ZONE_ANCHOR":
                # Replace the anchor token references for a zone.
                # parameters: {"anchor_word_ids": [...]}
                params = operation.parameters
                new_anchors = params.get("anchor_word_ids", [])
                state.compiled_zones = [
                    z.model_copy(update={"anchors_refs": new_anchors})
                    if z.zone_id == operation.target_zone_id else z
                    for z in state.compiled_zones
                ]

            elif op_type == "CALIBRATE_COORDINATES":
                # Record the drift correction (dx, dy) computed by AnchorCalibrationEngine.
                # parameters: {"dx": float, "dy": float, "anchor_word_ids": [...]}
                params = operation.parameters
                dx = float(params.get("dx", 0.0))
                dy = float(params.get("dy", 0.0))
                anchor_ids = params.get("anchor_word_ids", [])
                state.compiled_zones = [
                    z.model_copy(update={
                        "coordinate_drift": (dx, dy),
                        "anchors_refs": anchor_ids,
                    })
                    if z.zone_id == operation.target_zone_id else z
                    for z in state.compiled_zones
                ]

        elif isinstance(operation, FieldOperation):
            # Field value editing, override type, linking, etc.
            if op_type == "EDIT_VALUE":
                params = operation.parameters
                new_val = params["new_value"]
                # In HierarchicalFieldPair, let's find the pair and record edit
                # A simple way to mock value editing: update the alternative_answer_ids or metadata
                state.linked_fields = [
                    f.model_copy(update={"alternative_answer_ids": [new_val]}) if f.pair_id == operation.target_field_id else f
                    for f in state.linked_fields
                ]
                
            elif op_type == "OVERRIDE_FIELD_TYPE":
                params = operation.parameters
                new_type = params["new_type"]
                # Update inferred types list
                state.inferred_types = [
                    t.model_copy(update={"inferred_type": new_type}) if t.pair_id == operation.target_field_id else t
                    for t in state.inferred_types
                ]


# ────────────────────────────────────────────────────────────
# 3.3 SnapshotCompilerEngine (Gap#34)
# ────────────────────────────────────────────────────────────

class SnapshotStore:
    """Mock Persistent Snapshot Store (Gap#34)."""
    def __init__(self):
        self.blobs: Dict[str, CompiledSnapshot] = {}
        
    def write(self, snapshot: CompiledSnapshot):
        self.blobs[snapshot.snapshot_id] = snapshot
        
    def read(self, snapshot_id: str) -> Optional[CompiledSnapshot]:
        return self.blobs.get(snapshot_id)

class SnapshotCompilerEngine:
    """
    Compiles snapshots, writes to SnapshotStore, and manages in-memory limit.
    """
    def __init__(self, snapshot_store: SnapshotStore):
        self.store = snapshot_store
        self.memory_cache: Dict[str, CompiledSnapshot] = {}

    def compile(self, state: PageCompilationState) -> PageCompilationState:
        """
        Creates CompiledSnapshot, stores in SnapshotStore,
        and adds snapshot_id reference to PageCompilationState.
        """
        seq = len(state.ledger_operations)
        snap_id = f"snap_{state.page_metadata.page_id}_seq_{seq}"
        
        # Enforce sequence validation: reject write if seq <= existing
        for existing_snap_id in state.snapshots:
            existing_seq = int(existing_snap_id.split("_")[-1])
            if seq <= existing_seq:
                raise SnapshotRaceConditionError(
                    incoming_sequence_number=seq,
                    cached_sequence_number=existing_seq,
                    page_id=state.page_metadata.page_id,
                    timestamp=datetime.now(timezone.utc)
                )

        snapshot = CompiledSnapshot(
            snapshot_id=snap_id,
            page_id=state.page_metadata.page_id,
            ledger_sequence_number=seq,
            compiled_zones=state.compiled_zones,
            compiled_fields=state.linked_fields,
            composite_containers=state.composite_containers,
            schema_version=state.page_metadata.pipeline_version,
            created_at=datetime.now(timezone.utc)
        )
        
        # Store blob in external store (closes Gap#34)
        self.store.write(snapshot)
        
        # Cache snapshot in memory
        self.memory_cache[snap_id] = snapshot
        
        # Memory eviction: maximum 3 snapshot blobs in memory cache
        if len(self.memory_cache) > 3:
            # Evict oldest by timestamp or simple FIFO
            oldest_id = next(iter(self.memory_cache))
            del self.memory_cache[oldest_id]
            
        new_state = state.model_copy()
        new_state.snapshots = list(state.snapshots) + [snap_id]
        return new_state

    def load_snapshot(self, snapshot_id: str) -> CompiledSnapshot:
        """Loads a snapshot blob (first from memory cache, then from store)."""
        if snapshot_id in self.memory_cache:
            return self.memory_cache[snapshot_id]
            
        snapshot = self.store.read(snapshot_id)
        if not snapshot:
            raise KeyError(f"Snapshot {snapshot_id} not found in store.")
            
        # Add to cache (subject to the 3 cache limit)
        self.memory_cache[snapshot_id] = snapshot
        if len(self.memory_cache) > 3:
            oldest_id = next(iter(self.memory_cache))
            del self.memory_cache[oldest_id]
            
        return snapshot


# ────────────────────────────────────────────────────────────
# 1.12 SchemaMigrationAdapter & MIGRATION PROTOCOL (Gap#12)
# ────────────────────────────────────────────────────────────

class SchemaMigrationAdapterRunner:
    """
    Executes SchemaMigrationAdapter mapping for stale snapshots.
    """
    def run(self, snapshot: CompiledSnapshot, adapter: SchemaMigrationAdapter) -> CompiledSnapshot:
        migrated_fields = []
        for field in snapshot.compiled_fields:
            field_copy = field.model_copy()
            
            # Apply migration steps sequentially
            skip_field = False
            for step in adapter.migration_steps:
                action = step["action"]
                field_tag = step["field_tag"]
                
                # Check match against canonical_tag (via provenance or tag field if matches)
                # Field template matching tag
                # In HierarchicalFieldPair, we can match tag mapping if we look up mapped tag
                # Let's check matching logic
                if field_copy.pair_id == field_tag or (hasattr(field_copy, "zone_id") and field_copy.zone_id == field_tag):
                    if action == "rename":
                        new_tag = step["new_tag"]
                        field_copy = field_copy.model_copy(update={"pair_id": new_tag})
                    elif action == "drop":
                        skip_field = True
                        break
                    elif action == "default":
                        # Set custom default value on alternative_answer_ids
                        default_val = step["default_value"]
                        field_copy = field_copy.model_copy(update={"alternative_answer_ids": [str(default_val)]})
            
            if not skip_field:
                migrated_fields.append(field_copy)
                
        return snapshot.model_copy(update={
            "compiled_fields": migrated_fields,
            "schema_version": adapter.to_version
        })
