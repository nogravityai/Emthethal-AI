# ============================================================
# CFIS Hybrid Extraction Engine v3
# Location: backend/app/services/hybrid_extraction.py
#
# CORE INVARIANT (R16):
#   ALWAYS attempt native PDF text extraction before OCR.
#   OCR is fallback ONLY for:
#     - scanned pages (no text layer)
#     - rasterized regions
#     - image-only content
#     - low-confidence extraction regions
#
# Pipeline per page:
#   PDF Page
#   ├─ Detect native text layer (pdfplumber)
#   │   YES → NativeTokens (high fidelity, preserve coordinates)
#   │   NO  → mark as scanned
#   ├─ Scanned/Image pages → PaddleOCR → OCRTokens
#   └─ Return tokens with mode ("native" | "ocr")
#
# R14: Page-by-page loading — never load full PDF into RAM.
# R17: All coordinates in PAGE_PIXELS, normalized only at FormField.
# R19: ocr_raw_text is raw extraction — never semantic_label.
# R10: One bad page NEVER kills full document.
# ============================================================

from __future__ import annotations
import logging
import time
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image

from app.models.schemas import (
    CanonicalToken, BoundingBox, CoordinateSpace,
    ExtractionSource,
)
from app.services.legacy_geometry.text_clustering_engine import sort_tokens_deterministic

logger = logging.getLogger(__name__)

# Unicode ranges for Arabic presentation forms (visual-order encoded PDFs)
_ARABIC_PRESENTATION_A = (0xFB50, 0xFDFF)  # Arabic Presentation Forms-A
_ARABIC_PRESENTATION_B = (0xFE70, 0xFEFF)  # Arabic Presentation Forms-B


def _has_arabic_presentation_forms(text: str) -> bool:
    """Return True if text contains Arabic Presentation Form characters."""
    for ch in text:
        cp = ord(ch)
        if (_ARABIC_PRESENTATION_A[0] <= cp <= _ARABIC_PRESENTATION_A[1] or
                _ARABIC_PRESENTATION_B[0] <= cp <= _ARABIC_PRESENTATION_B[1]):
            return True
    return False


def _is_page_visually_encoded(words: List[dict]) -> bool:
    """
    Scan all words on the page to determine if the PDF's Arabic text 
    is visually encoded (reversed) rather than logically encoded.
    """
    for word_obj in words:
        text = word_obj.get("text", "").strip()
        if not text:
            continue
            
        # 1. Contains Arabic presentation forms
        if _has_arabic_presentation_forms(text):
            return True
            
        # 2. Word starts with characters that ONLY appear at the end of a logical Arabic word
        if text[0] in ('ة', 'ى'):
            return True
            
    return False


def _fix_arabic_text(text: str, is_reversed: bool = False) -> str:
    """
    Fix Arabic text extracted from visually-encoded PDFs.
    """
    if not is_reversed and not _has_arabic_presentation_forms(text):
        return text  # Normal PDF — do not touch

    # Step 1: Normalize presentation forms to base characters
    normalized = unicodedata.normalize('NFKC', text)

    # Step 2: Reverse visual text to logical text
    try:
        from bidi.algorithm import get_display
        # get_display is an involution for RTL: passing visual LTR returns logical RTL
        return get_display(normalized)
    except ImportError:
        # Fallback to simple word reversal if python-bidi is missing
        parts = normalized.split(' ')
        fixed = []
        for part in parts:
            if not part:
                fixed.append(part)
                continue
            arabic_count = sum(1 for c in part if '\u0600' <= c <= '\u06FF')
            if arabic_count / max(len(part), 1) > 0.3:
                fixed.append(part[::-1])
            else:
                fixed.append(part)  # English/numeric segment — keep as-is
        return ' '.join(fixed)

# Minimum character count to consider a page as having native text
NATIVE_TEXT_MIN_CHARS = 20

# DPI scale for PDF points → page_pixels conversion
# DPI=200, PDF points at 72 DPI → scale = 200/72
_DPI_SCALE = 200.0 / 72.0


# ── OCR ENGINE SINGLETON ────────────────────────────────────────────────────


@lru_cache(maxsize=2)
def _get_ocr_engine(language: str = "arabic") -> object:
    """
    Cached singleton OCR engine. Arabic is always default (R5).
    Models loaded from Docker volume at /root/.paddleocr.
    """
    import os
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")

    try:
        from paddleocr import PaddleOCR
        cfg = dict(
            use_angle_cls=True,
            use_gpu=False,
            enable_mkldnn=True,
            rec_batch_num=6,
            show_log=False,
            det_db_score_mode="slow",   # better for dense Arabic text
        )
        # Arabic is default; only use English model if explicitly forced
        cfg["lang"] = "arabic" if language in ("ar", "arabic", "ar_en", "mixed") else "en"
        logger.info(f"Loading OCR engine: lang={cfg['lang']}")
        return PaddleOCR(**cfg)
    except ImportError:
        logger.warning("paddleocr not available — OCR disabled")
        return None
    except Exception as e:
        logger.error(f"OCR engine init failed: {e}")
        return None


# ── NATIVE PDF TEXT EXTRACTION ──────────────────────────────────────────────


def _extract_native_tokens(
    page,                   # pdfplumber page object
    page_number: int,
    page_w_px: int,
    page_h_px: int,
) -> Tuple[List[CanonicalToken], bool]:
    """
    Extract text from a pdfplumber page object.
    Returns (tokens, has_native_text).

    Coordinates from pdfplumber are in PDF points (72 DPI).
    Converted to page_pixels: px = pts * (200 / 72).
    page_w_px and page_h_px are the image dimensions at DPI=200.
    """
    tokens = []

    pdf_width = float(page.width) if page.width else 1.0
    pdf_height = float(page.height) if page.height else 1.0
    scale_x = page_w_px / pdf_width
    scale_y = page_h_px / pdf_height

    logger.info(f"Page {page_number} coordinate space scaling: points ({pdf_width}x{pdf_height}) -> pixels ({page_w_px}x{page_h_px}). scale_x={scale_x:.4f}, scale_y={scale_y:.4f}")

    try:
        words = page.extract_words(
            x_tolerance=3,
            y_tolerance=3,
            keep_blank_chars=False,
        )
    except Exception as e:
        logger.warning(f"pdfplumber word extraction failed on page {page_number}: {e}")
        return [], False

    if not words:
        return [], False

    # Check if native text is substantial
    total_chars = sum(len(w.get("text", "")) for w in words)
    if total_chars < NATIVE_TEXT_MIN_CHARS:
        logger.info(
            f"Page {page_number}: native text too sparse ({total_chars} chars) → OCR fallback"
        )
        return [], False

    # Detect if the page is visually encoded (reversed)
    is_reversed_page = _is_page_visually_encoded(words)
    if is_reversed_page:
        logger.info(f"Page {page_number}: Visually-encoded (reversed) Arabic detected. Applying reversal logic.")

    for word in words:
        raw_text = word.get("text", "").strip()
        if not raw_text:
            continue

        # Fix Arabic presentation-form encoding and reversal
        text = _fix_arabic_text(raw_text, is_reversed_page)

        # Convert PDF points → page_pixels dynamically
        x0 = float(word.get("x0", 0)) * scale_x
        y0 = float(word.get("top", 0)) * scale_y
        x1 = float(word.get("x1", 0)) * scale_x
        y1 = float(word.get("bottom", 0)) * scale_y

        # Clamp to page bounds
        x0 = max(0.0, min(x0, page_w_px - 1))
        y0 = max(0.0, min(y0, page_h_px - 1))
        x1 = max(0.0, min(x1, float(page_w_px)))
        y1 = max(0.0, min(y1, float(page_h_px)))

        if x1 <= x0 or y1 <= y0:
            continue

        bbox = BoundingBox(
            x1=x0, y1=y0, x2=x1, y2=y1,
            coordinate_space=CoordinateSpace.PAGE_PIXELS,
            page_width=page_w_px,
            page_height=page_h_px,
        )
        tokens.append(CanonicalToken(
            ocr_raw_text=text,           # R19: raw text only
            bbox=bbox,
            confidence=1.0,              # native text = full confidence
            page_number=page_number,
            source=ExtractionSource.NATIVE,
            angle_corrected=False,
            extraction_language="native",
        ))

    logger.info(f"Page {page_number}: {len(tokens)} native tokens extracted")
    return tokens, len(tokens) > 0


# ── OCR EXTRACTION (FALLBACK) ───────────────────────────────────────────────


def _ocr_single_page(
    image: Image.Image,
    page_number: int,
    page_w_px: int,
    page_h_px: int,
    language: str = "arabic",
) -> List[CanonicalToken]:
    """
    Run OCR on a PIL Image. Returns CanonicalTokens in PAGE_PIXELS space.
    Wrapped in try/except — one bad page NEVER kills the document. (R10)
    Arabic is default OCR language. (R5)
    """
    ocr = _get_ocr_engine(language)
    if ocr is None:
        logger.error(f"OCR engine unavailable — page {page_number} skipped")
        return []

    img_array = np.array(image)
    tokens = []

    try:
        result = ocr.ocr(img_array, cls=True)
    except Exception as e:
        logger.error(f"OCR failed on page {page_number}: {e}")
        return []

    if not result:
        return []

    for result_page in result:
        if result_page is None:
            continue
        for item in result_page:
            if item is None or not isinstance(item, (list, tuple)) or len(item) < 2:
                continue

            bbox_points = item[0]   # [[x1,y1],[x2,y1],[x2,y2],[x1,y2]]
            text_conf = item[1]     # (text, confidence)

            if not bbox_points or not text_conf:
                continue

            try:
                text = str(text_conf[0]).strip()
                confidence = float(text_conf[1]) if len(text_conf) > 1 else 0.5
            except (IndexError, TypeError, ValueError):
                continue

            if not text:
                continue

            # Convert 4-point polygon → axis-aligned bbox
            try:
                xs = [float(p[0]) for p in bbox_points]
                ys = [float(p[1]) for p in bbox_points]
                x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
            except (IndexError, TypeError, ValueError):
                continue

            # Clamp to page bounds
            x1 = max(0.0, min(x1, page_w_px - 1))
            y1 = max(0.0, min(y1, page_h_px - 1))
            x2 = max(0.0, min(x2, float(page_w_px)))
            y2 = max(0.0, min(y2, float(page_h_px)))

            if x2 <= x1 or y2 <= y1:
                continue

            bbox = BoundingBox(
                x1=x1, y1=y1, x2=x2, y2=y2,
                coordinate_space=CoordinateSpace.PAGE_PIXELS,
                page_width=page_w_px,
                page_height=page_h_px,
            )
            tokens.append(CanonicalToken(
                ocr_raw_text=text,      # R19: raw OCR text, never semantic_label
                bbox=bbox,
                confidence=confidence,
                page_number=page_number,
                source=ExtractionSource.OCR,
                angle_corrected=False,
                extraction_language=language,
            ))

    logger.info(f"Page {page_number}: {len(tokens)} OCR tokens extracted")
    return tokens


# ── PAGE EXTRACTION ORCHESTRATOR ────────────────────────────────────────────


def extract_page_tokens(
    pdf_page,           # pdfplumber page object
    page_image: Image.Image,
    page_number: int,
    page_w_px: int,
    page_h_px: int,
    language: str = "arabic",
    force_ocr: bool = False,
) -> Tuple[List[CanonicalToken], str]:
    """
    Extract tokens from ONE page. Returns (tokens, mode).
    mode: "native" | "ocr" | "hybrid"

    R16 invariant: ALWAYS try native first.
    force_ocr=True bypasses native check (for debugging only).
    """
    if not force_ocr:
        # R16: Try native text extraction first
        native_tokens, has_native = _extract_native_tokens(
            pdf_page, page_number, page_w_px, page_h_px
        )
        if has_native:
            return native_tokens, "native"

    # Native failed or force_ocr — use OCR
    ocr_tokens = _ocr_single_page(page_image, page_number, page_w_px, page_h_px, language)
    return ocr_tokens, "ocr"
