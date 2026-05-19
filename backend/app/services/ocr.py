# ============================================================
# CFIS OCR Pipeline Orchestrator v3
# Location: backend/app/services/ocr.py
#
# THE ONLY ENTRY POINT for PDF processing.
# PDF → HybridExtraction → CanonicalTokens → LayoutCells → FormFields → DocumentOutput
#
# R10: Page-level fault isolation.
# R13: Tokens sorted (page, y1, x1) before clustering.
# R14: Page-by-page loading — never load full PDF into RAM.
# R16: Native text extraction attempted first via pdfplumber.
# R17: All final FormField bboxes in NORMALIZED space.
# ============================================================

from __future__ import annotations
import logging
import time
from pathlib import Path
from typing import List, Optional, Dict, Any

from app.models.schemas import (
    CanonicalToken, DocumentOutput, FormField,
    TemplateFingerprint, PageDimension, CoordinateSpace,
    ExtractionSource, BoundingBox,
)
from app.services.hybrid_extraction import extract_page_tokens
from app.services.legacy_geometry.text_clustering_engine import (
    detect_language, compute_document_geometry,
    sort_tokens_deterministic, build_layout_cells, auto_classify_widget,
)

logger = logging.getLogger(__name__)


def _cells_to_fields(cells, primary_language: str) -> List[FormField]:
    """
    Convert LayoutCells to FormFields.
    - Converts bbox from PAGE_PIXELS → NORMALIZED (R17)
    - Classifies widget type from merged_text
    - Flags low-confidence cells for QA
    - R19: semantic_label is derived from cell text, NOT assigned = ocr_raw_text
    """
    is_rtl = primary_language in ("ar", "ar_en")
    fields = []

    for cell in cells:
        # R17: normalize bbox before creating FormField
        norm_bbox = cell.bbox.to_normalized()

        widget = auto_classify_widget(cell.merged_text)

        # Heuristic: label = first line if multi-line, else full text
        label_text = cell.merged_text.split("\n")[0].strip() or cell.merged_text[:80]

        # Clean up labels for checkboxes if they have symbols inside
        if widget == "checkbox":
            import re
            label_text = re.sub(r'(?:□|☐|☑|✓|✗|\[\s*\]|\(\s*\))', '', label_text).strip()
            if not label_text:
                label_text = "اختيار"

        needs_qa = cell.avg_confidence < 0.65

        field = FormField(
            cell_id=cell.cell_id,
            semantic_label=label_text,         # R19: derived, not = raw ocr token
            semantic_label_ar=label_text if is_rtl else None,
            semantic_label_en=None,
            bbox=norm_bbox,                    # NORMALIZED (validator enforces this)
            row_index=cell.row_index,
            column_index=cell.column_index,
            page_number=cell.page_number,
            language=primary_language,
            is_rtl=is_rtl,
            runtime_widget=widget,
            confidence=cell.avg_confidence,
            needs_qa=needs_qa,
            human_corrected=False,
            source=cell.source,
        )
        fields.append(field)

    return _group_checkboxes_into_selects(fields)


def _group_checkboxes_into_selects(fields: List[FormField]) -> List[FormField]:
    """
    Looks for a Label followed by multiple Checkboxes on the same row.
    Merges them into a single 'select' (or 'radio') field with options.
    """
    grouped_fields = []
    
    from collections import defaultdict
    rows = defaultdict(list)
    for f in fields:
        rows[f.row_index].append(f)
        
    for row_idx in sorted(rows.keys()):
        row_fields = rows[row_idx]
        # In RTL, column_index 0 is rightmost. Sort ascending for visual RTL.
        row_fields.sort(key=lambda f: f.column_index)
        
        merged_row = []
        i = 0
        while i < len(row_fields):
            curr = row_fields[i]
            
            # If current field is a label (text, number, date) ending with :
            if curr.runtime_widget in ("text", "number", "date", "checkbox"):
                options = []
                j = i + 1
                while j < len(row_fields):
                    nxt = row_fields[j]
                    
                    # Stop if we hit a new label ending with :
                    if nxt.semantic_label and nxt.semantic_label.strip().endswith(':'):
                        break
                        
                    # It's an option if it's a checkbox, or short text (like "غير محدد")
                    is_option = False
                    if nxt.runtime_widget == "checkbox":
                        is_option = True
                    elif nxt.runtime_widget == "text" and len(nxt.semantic_label) < 20:
                        is_option = True
                        
                    if is_option:
                        opt_text = nxt.semantic_label.replace('اختيار', '').strip() or f"خيار {len(options)+1}"
                        options.append((opt_text, nxt))
                        j += 1
                    else:
                        break
                
                # If we found at least 2 options, OR 1 option and label ends with ':'
                is_label_with_colon = curr.semantic_label and curr.semantic_label.strip().endswith(':')
                if len(options) >= 2 or (len(options) == 1 and is_label_with_colon):
                    # Convert curr to select
                    curr.runtime_widget = "select"
                    curr.options_ar = [opt[0] for opt in options]
                    
                    # Expand bbox
                    all_bboxes = [curr.bbox] + [opt[1].bbox for opt in options]
                    curr.bbox.x1 = min(b.x1 for b in all_bboxes)
                    curr.bbox.y1 = min(b.y1 for b in all_bboxes)
                    curr.bbox.x2 = max(b.x2 for b in all_bboxes)
                    curr.bbox.y2 = max(b.y2 for b in all_bboxes)
                    
                    # Clean label
                    if curr.semantic_label:
                        curr.semantic_label = curr.semantic_label.replace(':', '').strip()
                        if curr.semantic_label_ar:
                            curr.semantic_label_ar = curr.semantic_label_ar.replace(':', '').strip()
                            
                    merged_row.append(curr)
                    i = j
                    continue
                    
            merged_row.append(curr)
            i += 1
            
        grouped_fields.extend(merged_row)
        
    return grouped_fields


def process_pdf(
    pdf_path: str,
    dpi: int = 200,
    language: str = "arabic",
    force_ocr: bool = False,
) -> DocumentOutput:
    """
    THE ONLY ENTRY POINT for PDF processing.

    R10: Page-level fault isolation.
    R13: Tokens sorted (page, y1, x1) before clustering.
    R14: Page-by-page loading.
    R16: Native text extraction attempted first.
    R17: All final bboxes in normalized space.
    """
    import pdfplumber
    from pdf2image import convert_from_path

    pdf_path = str(pdf_path)
    source_file = Path(pdf_path).name
    start_time = time.monotonic()

    all_tokens: List[CanonicalToken] = []
    page_dimensions: List[PageDimension] = []
    failed_pages: List[int] = []
    warnings: List[str] = []
    extraction_stats: Dict[str, Any] = {
        "native_pages": 0, "ocr_pages": 0, "hybrid_pages": 0,
        "total_native_tokens": 0, "total_ocr_tokens": 0,
        "force_ocr": force_ocr,
    }

    try:
        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)

            # R14: Convert pages to images via generator (page-by-page)
            page_images = convert_from_path(pdf_path, dpi=dpi)

            for page_num, (pdf_page, page_image) in enumerate(
                zip(pdf.pages, page_images)
            ):
                try:
                    pw, ph = page_image.size

                    page_tokens, mode = extract_page_tokens(
                        pdf_page=pdf_page,
                        page_image=page_image,
                        page_number=page_num,
                        page_w_px=pw,
                        page_h_px=ph,
                        language=language,
                        force_ocr=force_ocr,
                    )

                    has_native = mode == "native"
                    page_dimensions.append(PageDimension(
                        page_number=page_num,
                        width_px=pw,
                        height_px=ph,
                        width_pts=float(pdf_page.width) if pdf_page.width else None,
                        height_pts=float(pdf_page.height) if pdf_page.height else None,
                        has_native_text=has_native,
                    ))

                    if mode == "native":
                        extraction_stats["native_pages"] += 1
                        extraction_stats["total_native_tokens"] += len(page_tokens)
                    else:
                        extraction_stats["ocr_pages"] += 1
                        extraction_stats["total_ocr_tokens"] += len(page_tokens)

                    all_tokens.extend(page_tokens)
                    del page_image  # R14: free RAM immediately

                except Exception as e:
                    logger.error(f"Failed page {page_num}: {e}", exc_info=True)
                    failed_pages.append(page_num)
                    warnings.append(f"Page {page_num} failed: {str(e)[:120]}")

    except Exception as e:
        logger.error(f"PDF open failed: {e}", exc_info=True)
        raise ValueError(f"Cannot open PDF '{source_file}': {e}")

    # Compute extraction mode for fingerprint
    n_native = extraction_stats["native_pages"]
    n_ocr = extraction_stats["ocr_pages"]
    total_proc = n_native + n_ocr
    if total_proc == 0:
        extraction_mode = "hybrid"
    elif n_native == total_proc:
        extraction_mode = "native"
    elif n_ocr == total_proc:
        extraction_mode = "ocr"
    else:
        extraction_mode = "hybrid"
        extraction_stats["hybrid_pages"] = total_proc

    # Handle empty result (R10)
    if not all_tokens:
        total_pages_final = len(page_dimensions) if page_dimensions else 0
        warnings.append("No tokens extracted from any page.")
        fp = TemplateFingerprint.compute(
            page_count=total_pages_final,
            avg_confidence=0.0,
            col_count=0,
            median_row_height=0.0,
            median_col_gap=0.0,
            extraction_mode=extraction_mode,
        )
        return DocumentOutput(
            source_file=source_file,
            fingerprint=fp,
            primary_language="ar",
            total_pages=total_pages_final,
            failed_pages=failed_pages,
            processing_warnings=warnings,
            page_dimensions=page_dimensions,
            extraction_stats=extraction_stats,
        )

    # R13: Sort deterministically before clustering
    all_tokens = sort_tokens_deterministic(all_tokens)

    # Detect primary language
    primary_language = detect_language([t.ocr_raw_text for t in all_tokens])
    is_rtl = primary_language in ("ar", "ar_en")

    # Compute document geometry (zero hardcoded — R4)
    bboxes = [t.bbox.to_list() for t in all_tokens]
    geo = compute_document_geometry(bboxes)

    # Build layout cells (DBSCAN clustering)
    layout_cells = build_layout_cells(all_tokens, geo, is_rtl=is_rtl)

    # Convert LayoutCells → FormFields (bbox normalized — R17)
    fields = _cells_to_fields(layout_cells, primary_language)

    # Compute fingerprint
    col_count = max((c.column_index for c in layout_cells), default=0) + 1
    row_count = max((c.row_index for c in layout_cells), default=0) + 1
    avg_conf = (
        sum(t.confidence for t in all_tokens) / len(all_tokens)
        if all_tokens else 0.0
    )

    fp = TemplateFingerprint.compute(
        page_count=len(page_dimensions),
        avg_confidence=avg_conf,
        col_count=col_count,
        median_row_height=geo["row_height"],
        median_col_gap=geo["col_gap"],
        total_tokens=len(all_tokens),
        primary_language=primary_language,
        row_count=row_count,
        extraction_mode=extraction_mode,
    )

    qa_issues = sum(1 for f in fields if f.needs_qa)

    elapsed = time.monotonic() - start_time
    extraction_stats["processing_time_s"] = round(elapsed, 2)
    extraction_stats["total_tokens"] = len(all_tokens)
    extraction_stats["total_cells"] = len(layout_cells)
    extraction_stats["total_fields"] = len(fields)
    extraction_stats["extraction_mode"] = extraction_mode

    return DocumentOutput(
        source_file=source_file,
        fingerprint=fp,
        primary_language=primary_language,
        total_pages=len(page_dimensions),
        qa_status="pending",
        qa_issues_count=qa_issues,
        fields=fields,
        page_dimensions=page_dimensions,
        failed_pages=failed_pages,
        processing_warnings=warnings,
        extraction_stats=extraction_stats,
    )
