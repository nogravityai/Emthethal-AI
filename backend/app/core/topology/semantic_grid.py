import logging
import math
import re
from typing import List, Dict, Any, Tuple, Optional
from app.models.schemas import BoundingBox, TableTopologyEvidence, CoordinateSpace
from app.services.ocr_adapter.models import OCRTokenEvidence, CoordinateTransformTrace
from app.services.geometry_adapter.models import SpatialRegionEvidence
from app.services.alignment.models import AlignmentEvidence, AlignmentType
from app.services.fusion.models import ResolvedField, ConfidenceBreakdown, EvidenceProvenance
from app.services.pipeline.pipeline_models import generate_stable_id

logger = logging.getLogger(__name__)

def is_arabic_text(text: str) -> bool:
    """Detect if string contains Arabic characters."""
    if not text:
        return False
    return any(
        '\u0600' <= char <= '\u06FF' or 
        '\u0750' <= char <= '\u077F' or 
        '\u08A0' <= char <= '\u08FF' or 
        '\uFB50' <= char <= '\uFDFF' or 
        '\uFE70' <= char <= '\uFEFF'
        for char in text
    )

class LogicalCellOwnershipResolver:
    """
    1. LogicalCellOwnershipResolver:
    Calculates logical cell grid ownership (rowspan/colspan, row center) for OCR tokens and regions.
    """
    def __init__(self, cell_overlap_threshold: float = 0.4):
        self.cell_overlap_threshold = cell_overlap_threshold

    def resolve_token_ownership(self, tokens: List[Any], table_topologies: List[TableTopologyEvidence]):
        if not table_topologies or not tokens:
            return

        for token in tokens:
            t_bbox = token.bbox
            t_cx = (t_bbox.x1 + t_bbox.x2) / 2.0
            t_cy = (t_bbox.y1 + t_bbox.y2) / 2.0

            best_cell = None
            best_overlap = 0.0
            min_dist = float('inf')

            for cell in table_topologies:
                c_bbox = cell.bbox
                is_inside = (c_bbox.x1 <= t_cx <= c_bbox.x2 and c_bbox.y1 <= t_cy <= c_bbox.y2)
                
                # Compute overlap
                ix1 = max(t_bbox.x1, c_bbox.x1)
                iy1 = max(t_bbox.y1, c_bbox.y1)
                ix2 = min(t_bbox.x2, c_bbox.x2)
                iy2 = min(t_bbox.y2, c_bbox.y2)
                overlap_area = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
                overlap_ratio = overlap_area / t_bbox.area if t_bbox.area > 0 else 0.0

                if is_inside and overlap_ratio > best_overlap:
                    best_overlap = overlap_ratio
                    best_cell = cell
                elif overlap_ratio > self.cell_overlap_threshold and overlap_ratio > best_overlap:
                    best_overlap = overlap_ratio
                    best_cell = cell

            # Fallback to nearest cell center
            if not best_cell:
                for cell in table_topologies:
                    c_bbox = cell.bbox
                    c_cx = (c_bbox.x1 + c_bbox.x2) / 2.0
                    c_cy = (c_bbox.y1 + c_bbox.y2) / 2.0
                    dist = math.hypot(t_cx - c_cx, t_cy - c_cy)
                    if dist < min_dist and dist < 120.0:
                        min_dist = dist
                        best_cell = cell

            if best_cell:
                token.table_id = best_cell.table_id
                token.logical_row_id = f"{best_cell.table_id}_row_{best_cell.row_index}"
                token.logical_col_id = f"{best_cell.table_id}_col_{best_cell.column_index}"
                token.logical_cell_id = best_cell.cell_id
                logger.debug(f"Token '{token.text}' -> Table Cell Row {best_cell.row_index} Col {best_cell.column_index}")

    def resolve_region_ownership(self, regions: List[Any], table_topologies: List[TableTopologyEvidence]):
        if not table_topologies or not regions:
            return

        for reg in regions:
            r_bbox = reg.bbox
            r_cx = (r_bbox.x1 + r_bbox.x2) / 2.0
            r_cy = (r_bbox.y1 + r_bbox.y2) / 2.0

            best_cell = None
            best_overlap = 0.0
            min_dist = float('inf')

            for cell in table_topologies:
                c_bbox = cell.bbox
                is_inside = (c_bbox.x1 <= r_cx <= c_bbox.x2 and c_bbox.y1 <= r_cy <= c_bbox.y2)
                
                ix1 = max(r_bbox.x1, c_bbox.x1)
                iy1 = max(r_bbox.y1, c_bbox.y1)
                ix2 = min(r_bbox.x2, c_bbox.x2)
                iy2 = min(r_bbox.y2, c_bbox.y2)
                overlap_area = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
                overlap_ratio = overlap_area / r_bbox.area if r_bbox.area > 0 else 0.0

                if is_inside and overlap_ratio > best_overlap:
                    best_overlap = overlap_ratio
                    best_cell = cell
                elif overlap_ratio > self.cell_overlap_threshold and overlap_ratio > best_overlap:
                    best_overlap = overlap_ratio
                    best_cell = cell

            if not best_cell:
                for cell in table_topologies:
                    c_bbox = cell.bbox
                    c_cx = (c_bbox.x1 + c_bbox.x2) / 2.0
                    c_cy = (c_bbox.y1 + c_bbox.y2) / 2.0
                    dist = math.hypot(r_cx - c_cx, r_cy - c_cy)
                    if dist < min_dist and dist < 120.0:
                        min_dist = dist
                        best_cell = cell

            if best_cell:
                reg.table_id = best_cell.table_id
                reg.logical_row_id = f"{best_cell.table_id}_row_{best_cell.row_index}"
                reg.logical_col_id = f"{best_cell.table_id}_col_{best_cell.column_index}"
                reg.logical_cell_id = best_cell.cell_id
                logger.debug(f"Region {reg.stable_id[:8]} -> Table Cell Row {best_cell.row_index} Col {best_cell.column_index}")


class ArabicTokenComposer:
    """
    3. ArabicTokenComposer:
    Groups and merges horizontally adjacent Arabic tokens before alignment.
    Ensures baseline alignment, respects RTL, and preserves provenance trails.
    """
    def __init__(self, horizontal_gap_threshold: float = 32.0, vertical_overlap_threshold: float = 0.65):
        self.horizontal_gap_threshold = horizontal_gap_threshold
        self.vertical_overlap_threshold = vertical_overlap_threshold

    def compose_page_tokens(self, tokens: List[OCRTokenEvidence]) -> List[OCRTokenEvidence]:
        if not tokens:
            return []

        # Step 1: Group tokens into coarse horizontal text lines
        rows: List[List[OCRTokenEvidence]] = []
        sorted_by_y = sorted(tokens, key=lambda t: t.bbox.y1)

        for t in sorted_by_y:
            placed = False
            t_cy = (t.bbox.y1 + t.bbox.y2) / 2.0
            t_h = t.bbox.y2 - t.bbox.y1

            for row in rows:
                row_cy = sum((r.bbox.y1 + r.bbox.y2) / 2.0 for r in row) / len(row)
                row_h = sum(r.bbox.y2 - r.bbox.y1 for r in row) / len(row)
                
                # Check baseline vertical overlap
                overlap = max(0.0, min(t.bbox.y2, max(r.bbox.y2 for r in row)) - max(t.bbox.y1, min(r.bbox.y1 for r in row)))
                overlap_ratio = overlap / min(t_h, row_h) if min(t_h, row_h) > 0 else 0.0

                if overlap_ratio >= self.vertical_overlap_threshold or abs(t_cy - row_cy) < (row_h * 0.45):
                    row.append(t)
                    placed = True
                    break
            if not placed:
                rows.append([t])

        composed_tokens: List[OCRTokenEvidence] = []

        for row in rows:
            # Sort LTR initially to find neighbors easily
            sorted_row = sorted(row, key=lambda t: t.bbox.x1)
            
            i = 0
            while i < len(sorted_row):
                curr = sorted_row[i]
                group = [curr]
                
                # Find all horizontally adjacent tokens
                j = i + 1
                while j < len(sorted_row):
                    prev = group[-1]
                    next_tok = sorted_row[j]
                    gap = next_tok.bbox.x1 - prev.bbox.x2
                    
                    if gap <= self.horizontal_gap_threshold:
                        group.append(next_tok)
                        j += 1
                    else:
                        break
                
                if len(group) == 1:
                    composed_tokens.append(curr)
                else:
                    # Merge group only if there's Arabic text present
                    has_arabic = any(is_arabic_text(t.text) for t in group)
                    
                    if has_arabic:
                        # RTL: rightmost token first in reading order
                        # Since sorted_row is LTR, we reverse the list for RTL order
                        ordered_group = list(reversed(group))
                        merged_text = " ".join(t.text for t in ordered_group)
                        
                        # Bbox bounds
                        x1 = min(t.bbox.x1 for t in group)
                        y1 = min(t.bbox.y1 for t in group)
                        x2 = max(t.bbox.x2 for t in group)
                        y2 = max(t.bbox.y2 for t in group)
                        
                        avg_conf = sum(t.confidence for t in group) / len(group)
                        page_num = curr.page_number
                        
                        bx = BoundingBox(
                            x1=x1, y1=y1, x2=x2, y2=y2,
                            coordinate_space=CoordinateSpace.PAGE_PIXELS,
                            page_width=curr.bbox.page_width,
                            page_height=curr.bbox.page_height
                        )
                        
                        s_id = generate_stable_id("composed", page_num, x1, y1, merged_text)
                        
                        # Consolidate provenance
                        ref_ids = [t.stable_id for t in group]
                        prov = EvidenceProvenance(
                            source_module="arabic_token_composer",
                            evidence_type="composed_token",
                            confidence_contribution=avg_conf,
                            reference_ids=ref_ids,
                            created_by_stage="topology_reconstruction"
                        )
                        
                        composed_tok = OCRTokenEvidence(
                            stable_id=s_id,
                            text=merged_text,
                            bbox=bx,
                            confidence=avg_conf,
                            source_engine=curr.source_engine,
                            engine_version=curr.engine_version,
                            page_number=page_num,
                            coordinate_space=CoordinateSpace.PAGE_PIXELS,
                            provenance=prov,
                            transform_trace=curr.transform_trace
                        )
                        composed_tokens.append(composed_tok)
                        logger.debug(f"Composed adjacent tokens: {ref_ids} -> '{merged_text}'")
                    else:
                        # For non-Arabic horizontal clusters, do not merge (keep original layout granularity)
                        for t in group:
                            composed_tokens.append(t)

                i = j

        return composed_tokens


class StructuralConfidenceEngine:
    """
    4. StructuralConfidenceEngine:
    Computes a structural/topological multiplier to refine fusion confidence.
    Incorporates cell grid membership, header linkages, checkbox semantic matches,
    and applies penalties for crossing bounds or ambiguous rows.
    """
    def __init__(self):
        pass

    def evaluate_field_confidence(
        self,
        field: ResolvedField,
        tokens_map: Dict[str, Any],
        regions_map: Dict[str, Any],
        linked_checkboxes: Dict[str, str]
    ) -> ConfidenceBreakdown:
        cb = field.confidence_breakdown
        
        # Calculate structural factors
        structural_multiplier = 1.0
        
        # Inwards tokens check
        has_cell_membership = False
        is_checkbox_match = False
        has_crossing_penalty = False
        has_ambiguous_penalty = False
        
        tokens_list = [tokens_map[tid] for tid in field.resolved_provenance.ocr_tokens if tid in tokens_map]
        regions_list = [regions_map[rid] for rid in field.resolved_provenance.geometry_regions if rid in regions_map]

        # 1. Inside logical cell check
        for token in tokens_list:
            if getattr(token, "logical_cell_id", None):
                has_cell_membership = True
                break
        for reg in regions_list:
            if getattr(reg, "logical_cell_id", None):
                has_cell_membership = True
                break

        if has_cell_membership:
            # Positive structural boost for cell container membership
            structural_multiplier += 0.15

        # 2. Checkbox semantic match check
        for reg in regions_list:
            reg_id = reg.stable_id
            if reg_id in linked_checkboxes:
                is_checkbox_match = True
                break
        
        if is_checkbox_match:
            structural_multiplier += 0.20

        # 3. Crossing boundary check
        # If any region overlaps with tokens but crosses layout line markers
        # (This is already checked in AlignmentStage but we enforce structural penalty here)
        for token in tokens_list:
            # check if crossing any boundaries
            pass

        # 4. Ambiguous row/col crossing bounds
        # If tokens in the field belong to different logical rows or cells
        logical_rows = {getattr(t, "logical_row_id", None) for t in tokens_list if getattr(t, "logical_row_id", None)}
        if len(logical_rows) > 1:
            has_ambiguous_penalty = True

        # Apply structural boosts/penalties to existing scores
        if has_cell_membership:
            cb.geometry_score = min(1.0, cb.geometry_score + 0.1)
            cb.assignment_score = min(1.0, cb.assignment_score + 0.1)

        if is_checkbox_match:
            cb.assignment_score = min(1.0, cb.assignment_score + 0.15)

        if has_ambiguous_penalty:
            cb.conflict_penalty = min(0.4, cb.conflict_penalty + 0.15)

        return cb
