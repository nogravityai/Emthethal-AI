# ============================================================
# CFIS Geometry Engine v3
# Dynamic clustering. Zero hardcoded geometry.
# All eps values derived from document's own statistics.
# R13: Elements sorted (page, y1, x1) before clustering — always.
# R18: PP-StructureV3 proposals normalized before use.
# Location: backend/app/services/geometry.py
# ============================================================

from __future__ import annotations
import logging
import re
from typing import List, Dict, Tuple, Optional

import numpy as np
from sklearn.cluster import DBSCAN

from app.models.schemas import (
    CanonicalToken, LayoutCell, BoundingBox, CoordinateSpace,
    ExtractionSource, LayoutProposal,
)

logger = logging.getLogger(__name__)


# ── LANGUAGE DETECTION ──────────────────────────────────────────────────────


def detect_language(texts: List[str]) -> str:
    """
    Heuristic language detection using Unicode ranges.
    Arabic Unicode block: U+0600–U+06FF
    Returns: "ar", "en", or "ar_en"
    """
    arabic_count = 0
    latin_count = 0
    for text in texts:
        for char in text:
            if '\u0600' <= char <= '\u06FF':
                arabic_count += 1
            elif 'a' <= char.lower() <= 'z':
                latin_count += 1

    total = arabic_count + latin_count
    if total == 0:
        return "ar"   # Arabic default (R5)
    ratio = arabic_count / total
    if ratio >= 0.65:
        return "ar"
    if ratio <= 0.30:
        return "en"
    return "ar_en"


# ── DOCUMENT GEOMETRY COMPUTATION ──────────────────────────────────────────


def _iqr_filter(arr: np.ndarray) -> np.ndarray:
    """Remove outliers using IQR method. Handles logos, stamps, noise boxes."""
    if len(arr) < 4:
        return arr
    q1, q3 = np.percentile(arr, [25, 75])
    iqr = q3 - q1
    mask = (arr >= q1 - 1.5 * iqr) & (arr <= q3 + 1.5 * iqr)
    filtered = arr[mask]
    return filtered if len(filtered) >= 2 else arr


def compute_document_geometry(bboxes: List[List[float]]) -> Dict[str, float]:
    """
    Compute document-specific geometric statistics from CanonicalToken bboxes.
    Called ONCE per document, before any clustering.

    Input:  list of [x1, y1, x2, y2] in page_pixels space
    Output: dict with eps_y, eps_x, row_height, col_gap

    NEVER returns hardcoded eps. Always document-derived. (R4)
    """
    if len(bboxes) < 3:
        logger.warning(f"Too few bboxes ({len(bboxes)}) — using safe defaults.")
        return {"eps_y": 15.0, "eps_x": 20.0, "row_height": 20.0, "col_gap": 30.0}

    heights = np.array([b[3] - b[1] for b in bboxes], dtype=float)
    x_starts = np.array([b[0] for b in bboxes], dtype=float)
    x_ends   = np.array([b[2] for b in bboxes], dtype=float)
    widths   = x_ends - x_starts

    valid_heights = _iqr_filter(heights[heights > 2])
    avg_row_height = float(np.median(valid_heights)) if len(valid_heights) > 0 else 20.0

    rounded_x = np.unique(np.round(x_starts / 5) * 5)
    if len(rounded_x) > 1:
        gaps = np.diff(rounded_x)
        valid_gaps = _iqr_filter(gaps[gaps > 3])
        median_col_gap = float(np.median(valid_gaps)) if len(valid_gaps) > 0 else 30.0
    else:
        median_col_gap = float(np.median(_iqr_filter(widths))) / 2.0

    result = {
        "eps_y":      max(8.0, avg_row_height * 0.65),
        "eps_x":      max(10.0, median_col_gap * 0.55),
        "row_height": avg_row_height,
        "col_gap":    median_col_gap,
    }
    logger.info(
        f"Document geometry: row_height={avg_row_height:.1f}, "
        f"col_gap={median_col_gap:.1f}, "
        f"eps_y={result['eps_y']:.1f}, eps_x={result['eps_x']:.1f}"
    )
    return result


# ── DETERMINISTIC SORTING (R13) ─────────────────────────────────────────────


def sort_tokens_deterministic(tokens: List[CanonicalToken]) -> List[CanonicalToken]:
    """Sort tokens by (page_number, bbox.y1, bbox.x1) for deterministic clustering. R13."""
    return sorted(tokens, key=lambda t: (t.page_number, t.bbox.y1, t.bbox.x1))


# ── DETERMINISTIC CLUSTERING (R13) ──────────────────────────────────────────


def cluster_rows(bboxes: List[List[float]], eps_y: float) -> List[int]:
    """
    Cluster bounding boxes into rows by y-center.
    Input MUST be pre-sorted by (y1, x1) for determinism. (R13)
    Returns stable 0-indexed row labels (top to bottom).
    """
    if not bboxes:
        return []
    y_centers = np.array([[(b[1] + b[3]) / 2.0] for b in bboxes], dtype=float)
    raw_labels = DBSCAN(eps=eps_y, min_samples=1).fit_predict(y_centers)

    cluster_y_means: Dict[int, List[float]] = {}
    for idx, lbl in enumerate(raw_labels):
        cluster_y_means.setdefault(int(lbl), []).append(float(y_centers[idx][0]))
    ordered = sorted(cluster_y_means.keys(), key=lambda l: np.mean(cluster_y_means[l]))
    label_map = {old: new for new, old in enumerate(ordered)}
    return [label_map[int(l)] for l in raw_labels]


def cluster_cols(
    bboxes: List[List[float]],
    eps_x: float,
    is_rtl: bool = True,
) -> List[int]:
    """
    Cluster bounding boxes into columns by x-center.
    For RTL documents: rightmost column = index 0.
    Input MUST be pre-sorted by (y1, x1) for determinism. (R13)
    """
    if not bboxes:
        return []
    x_centers = np.array([[(b[0] + b[2]) / 2.0] for b in bboxes], dtype=float)
    raw_labels = DBSCAN(eps=eps_x, min_samples=1).fit_predict(x_centers)

    cluster_x_means: Dict[int, List[float]] = {}
    for idx, lbl in enumerate(raw_labels):
        cluster_x_means.setdefault(int(lbl), []).append(float(x_centers[idx][0]))

    # Sort column labels: left-to-right first, then flip for RTL
    ordered = sorted(cluster_x_means.keys(), key=lambda l: np.mean(cluster_x_means[l]))
    if is_rtl:
        ordered = list(reversed(ordered))
    label_map = {old: new for new, old in enumerate(ordered)}
    return [label_map[int(l)] for l in raw_labels]


# ── WIDGET AUTO-CLASSIFICATION ───────────────────────────────────────────────

# Arabic digit mapping for normalization
_ARABIC_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')

# Checkbox patterns: empty box characters, blank-like patterns (allowing spaces)
_CHECKBOX_RE = re.compile(r'^[\s□☐☑✓✗\[\]\(\)\-_]{1,5}$')
_HAS_CHECKBOX_RE = re.compile(r'(?:^|\s)(?:□|☐|☑|✓|✗|\[\s*\]|\(\s*\))(?:\s|$)')

# Arabic date pattern: filled dates or empty date artifacts like / / 
_DATE_RE = re.compile(r'[\d٠-٩]{1,4}[/\-\.\\][\d٠-٩]{1,2}[/\-\.\\][\d٠-٩]{2,4}')
_EMPTY_DATE_RE = re.compile(r'([/\-\.\\]\s*){2,}')

# Pure numeric (Arabic or Latin)
_NUMBER_RE = re.compile(r'^[\d٠-٩\.,\s\+\-\%]{1,20}$')


def auto_classify_widget(text: str) -> str:
    """
    Auto-classify a cell's text content into a widget type.
    Handles both filled data and empty template artifacts via semantics.
    """
    if not text or not text.strip():
        return "text"

    t = text.strip()
    t_lower = t.lower()

    # 1. Empty Form Artifacts (Structural)
    if _CHECKBOX_RE.match(t) or _HAS_CHECKBOX_RE.search(t):
        return "checkbox"
    if _DATE_RE.search(t) or _EMPTY_DATE_RE.search(t):
        return "date"

    # 2. Semantic Keyword Matching (Arabic & English)
    if 'تاريخ' in t_lower or 'date' in t_lower:
        return "date"
    if 'رقم' in t_lower or 'number' in t_lower:
        return "number"
    if 'ملاحظ' in t_lower or 'notes' in t_lower or 'تفاصيل' in t_lower or 'وصف' in t_lower:
        return "textarea"

    # 3. Value-based matching (Filled forms)
    normalized = t.translate(_ARABIC_DIGITS)
    if _NUMBER_RE.match(normalized):
        return "number"

    # Multi-line / long text → textarea
    if '\n' in t or len(t) > 120:
        return "textarea"

    return "text"


# ── LAYOUT PROPOSAL NORMALIZATION (R18) ─────────────────────────────────────


def normalize_layout_proposal(
    proposal: LayoutProposal,
    page_width_px: int,
    page_height_px: int,
) -> LayoutProposal:
    """
    Normalize PP-StructureV3 layout proposals from PAGE_PIXELS → NORMALIZED.
    R18: proposals are not canonical truth — must be normalized + validated.
    Returns a new LayoutProposal with normalized=True.
    """
    normalized_regions = []
    for bbox in proposal.table_regions:
        if bbox.coordinate_space == CoordinateSpace.NORMALIZED:
            normalized_regions.append(bbox)
        else:
            # Ensure page dimensions match
            norm_bbox = BoundingBox(
                x1=bbox.x1, y1=bbox.y1, x2=bbox.x2, y2=bbox.y2,
                coordinate_space=bbox.coordinate_space,
                page_width=page_width_px,
                page_height=page_height_px,
            ).to_normalized()
            normalized_regions.append(norm_bbox)

    return LayoutProposal(
        page_number=proposal.page_number,
        table_regions=normalized_regions,
        confidence=proposal.confidence,
        normalized=True,
    )


# ── LAYOUT CELL BUILDER ──────────────────────────────────────────────────────


_FRAGMENT_RE = re.compile(r'^([\.\-\)]?\s*\d+\s*[\.\-\)]?|[\(\)\[\]/\\-]|م\d+|\d+م|م)$')

def compute_fragment_merge_threshold(geo: Dict[str, float], is_rtl: bool = True) -> float:
    """
    Dynamically compute the threshold for merging text fragments.
    For Arabic/RTL text, we use a much larger multiplier (2.4x) to aggressively
    consolidate cursive word fragments and nearby labels, preventing over-fragmentation.
    """
    multiplier = 2.4 if is_rtl else 1.5
    return geo["eps_x"] * multiplier


def build_row_clusters(tokens: List[CanonicalToken], eps_y: float) -> Dict[int, List[CanonicalToken]]:
    """Groups tokens into rows using DBSCAN clustering."""
    bboxes = [t.bbox.to_list() for t in tokens]
    row_labels = cluster_rows(bboxes, eps_y)
    
    row_groups: Dict[int, List[CanonicalToken]] = {}
    for token, row_lbl in zip(tokens, row_labels):
        row_groups.setdefault(row_lbl, []).append(token)
    return row_groups


def merge_fragments(
    row_tokens: List[CanonicalToken],
    base_eps_x: float,
    is_rtl: bool
) -> List[List[CanonicalToken]]:
    """
    Merges horizontally adjacent tokens into coherent blocks based on proximity and structural anchors.
    """
    sorted_tokens = sorted(row_tokens, key=lambda t: t.bbox.x1)
    
    merged_blocks = []
    current_block = [sorted_tokens[0]]
    
    for i in range(1, len(sorted_tokens)):
        prev_token = current_block[-1]
        curr_token = sorted_tokens[i]
        
        gap = curr_token.bbox.x1 - prev_token.bbox.x2
        
        prev_text = prev_token.ocr_raw_text.strip()
        curr_text = curr_token.ocr_raw_text.strip()
        
        is_prev_frag = bool(_FRAGMENT_RE.match(prev_text))
        is_curr_frag = bool(_FRAGMENT_RE.match(curr_text))
        
        # Aggressively merge ONLY numbering fragments, and limit the gap to 2.5x
        force_merge = (is_prev_frag or is_curr_frag) and gap < (base_eps_x * 2.5)
        
        if gap <= base_eps_x or force_merge:
            current_block.append(curr_token)
        else:
            merged_blocks.append(current_block)
            current_block = [curr_token]
            
    if current_block:
        merged_blocks.append(current_block)
        
    merged_blocks.sort(key=lambda block: block[0].bbox.x1)
    return merged_blocks


def build_layout_cells(
    tokens: List[CanonicalToken],
    geo: Dict[str, float],
    is_rtl: bool = True,
) -> List[LayoutCell]:
    """
    Phase 1.5 Orchestrator:
    Converts sorted CanonicalTokens into LayoutCells by orchestrating Modular Geometry Layers.
    """
    if not tokens:
        return []

    eps_y = geo["eps_y"]
    eps_x = compute_fragment_merge_threshold(geo, is_rtl)

    row_groups = build_row_clusters(tokens, eps_y)
    cells: List[LayoutCell] = []

    for row_idx, row_tokens in row_groups.items():
        page_num = row_tokens[0].page_number
        
        merged_blocks = merge_fragments(row_tokens, eps_x, is_rtl)
        
        for col_idx, block_tokens in enumerate(merged_blocks):
            if is_rtl:
                block_tokens_sorted = sorted(block_tokens, key=lambda t: (t.bbox.y1, -t.bbox.x1))
            else:
                block_tokens_sorted = sorted(block_tokens, key=lambda t: (t.bbox.y1, t.bbox.x1))

            merged_text = " ".join(t.ocr_raw_text for t in block_tokens_sorted).strip()

            # Filter out ghost fields (pure punctuation, lines, or isolated broken brackets)
            if not merged_text or re.match(r'^[\._\-\s/\\:]+$', merged_text) or re.match(r'^[\s\(\)\[\]]{1,2}$', merged_text):
                continue

            # Filter out ghost lines made of multiple checkboxes (e.g., ☐☐☐☐)
            if re.match(r'^[\s□☐☑✓✗]{3,}$', merged_text):
                continue

            # Filter out completely isolated fragments that failed to merge (e.g., "7)", "1.", "م20")
            if _FRAGMENT_RE.match(merged_text):
                continue

            x1 = min(t.bbox.x1 for t in block_tokens)
            y1 = min(t.bbox.y1 for t in block_tokens)
            x2 = max(t.bbox.x2 for t in block_tokens)
            y2 = max(t.bbox.y2 for t in block_tokens)

            pw = block_tokens[0].bbox.page_width
            ph = block_tokens[0].bbox.page_height

            sources = [t.source for t in block_tokens]
            dom_source = ExtractionSource.NATIVE if sources.count(ExtractionSource.NATIVE) > len(sources) // 2 else ExtractionSource.OCR
            avg_conf = sum(t.confidence for t in block_tokens) / len(block_tokens)

            final_col_idx = (len(merged_blocks) - 1 - col_idx) if is_rtl else col_idx

            cells.append(LayoutCell(
                merged_text=merged_text,
                bbox=BoundingBox(
                    x1=x1, y1=y1, x2=x2, y2=y2,
                    coordinate_space=CoordinateSpace.PAGE_PIXELS,
                    page_width=pw,
                    page_height=ph,
                ),
                row_index=row_idx,
                column_index=final_col_idx,
                page_number=page_num,
                token_count=len(block_tokens),
                avg_confidence=avg_conf,
                source=dom_source,
            ))

    cells.sort(key=lambda c: (c.page_number, c.row_index, c.column_index))
    return cells
