# ============================================================
# CFIS Phase 2 — Visual Geometry Engine
# Location: backend/app/core/geometry/visual_geometry.py
#
# PURPOSE: Extract visual geometric primitives from page images
# using a strict deterministic OpenCV pipeline.
#
# PIPELINE ORDER (mandatory, no deviations):
#   Adaptive Threshold
#   → Morphology (kernel-based H/V isolation)
#   → Connected Components + Contour Cleanup
#   → Line Extraction via contour bounding rects
#   → Hough Refinement (post-filter only, not primary source)
#
# RULE 2: Geometry is probabilistic, Text is Truth.
#   OpenCV outputs CONSTRAIN and SCORE hypotheses. They NEVER
#   override valid native text extraction.
#
# RULE 5: ALL primitives are projected back to PAGE_PIXELS
#   immediately after extraction using CoordinateTransformTrace.
#
# RULE 7: ALL OpenCV operations execute on TARGET_DPI=300 images.
# ============================================================

from __future__ import annotations

import logging
import math
from typing import List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image
from pydantic import BaseModel, Field

from app.models.schemas import BoundingBox, CoordinateSpace
from app.services.coordinate_trace import CoordinateTransformTrace, TARGET_DPI

logger = logging.getLogger(__name__)


# ── PRIMITIVES ────────────────────────────────────────────────────────────────


class DetectedLine(BaseModel):
    """
    A line primitive extracted from the image via morphology+contours.
    Coordinates are ALWAYS in PAGE_PIXELS (projected back immediately).
    """
    x1: float
    y1: float
    x2: float
    y2: float
    orientation: str  # "horizontal" | "vertical"
    thickness: float  # line thickness in PAGE_PIXELS
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    trace: CoordinateTransformTrace

    @property
    def length(self) -> float:
        return math.hypot(self.x2 - self.x1, self.y2 - self.y1)


class DetectedBox(BaseModel):
    """
    A rectangular region detected via contour analysis.
    bbox is ALWAYS in PAGE_PIXELS space.
    """
    bbox: BoundingBox
    box_type: str  # "checkbox" | "table_cell" | "input_box" | "signature_box" | "image_region"
    confidence: float = Field(ge=0.0, le=1.0)
    fill_ratio: float = Field(ge=0.0, le=1.0, default=0.0)
    shape_score: float = Field(ge=0.0, le=1.0, default=0.0)
    trace: CoordinateTransformTrace


# ── DPI NORMALIZATION (Rule 7) ────────────────────────────────────────────────


def normalize_image_dpi(
    pil_image: Image.Image,
    source_dpi: float = 200.0,
) -> Tuple[np.ndarray, CoordinateTransformTrace]:
    """
    Scale the image to TARGET_DPI (300) before ANY OpenCV processing.
    This is mandatory — Rule 7.

    Returns:
        cv_image: OpenCV BGR image at TARGET_DPI resolution
        trace: CoordinateTransformTrace for projecting primitives back to PAGE_PIXELS
    """
    trace = CoordinateTransformTrace.from_dpi_normalization(
        source_dpi=source_dpi,
        source_width_px=pil_image.width,
        source_height_px=pil_image.height,
    )

    new_w = int(pil_image.width * trace.scale_x)
    new_h = int(pil_image.height * trace.scale_y)

    resized = pil_image.resize((new_w, new_h), Image.Resampling.LANCZOS)
    cv_arr = np.array(resized)

    if len(cv_arr.shape) == 3 and cv_arr.shape[2] == 3:
        cv_arr = cv_arr[:, :, ::-1].copy()  # RGB → BGR
    elif len(cv_arr.shape) == 3 and cv_arr.shape[2] == 4:
        cv_arr = cv2.cvtColor(cv_arr, cv2.COLOR_RGBA2BGR)

    logger.debug(
        f"normalize_image_dpi: {pil_image.size} @{source_dpi}dpi → "
        f"({new_w},{new_h}) @{TARGET_DPI}dpi (scale={trace.scale_x:.4f})"
    )
    return cv_arr, trace


# ── INTERNAL HELPERS ──────────────────────────────────────────────────────────


def _to_grayscale(cv_image: np.ndarray) -> np.ndarray:
    if len(cv_image.shape) == 2:
        return cv_image
    return cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)


def _adaptive_threshold(gray: np.ndarray) -> np.ndarray:
    """
    Adaptive Gaussian threshold — robust against uneven illumination.
    Ink pixels → 255 (white). Background → 0 (black).
    """
    return cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        blockSize=15,
        C=5,
    )


def cleanup_contours(
    binary: np.ndarray,
    min_area: float = 25.0,
) -> np.ndarray:
    """
    Remove noise contours below min_area pixels.
    Returns a cleaned binary mask with small blobs erased.
    """
    output = np.zeros_like(binary)
    cnts, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnts:
        if cv2.contourArea(c) >= min_area:
            cv2.drawContours(output, [c], -1, 255, thickness=cv2.FILLED)
    return output


def extract_connected_components(
    binary: np.ndarray,
    min_area: float = 50.0,
) -> List[Tuple[int, int, int, int]]:
    """
    Extract connected component bounding rectangles from a binary mask.
    Returns list of (x, y, w, h) in OPENCV (DPI-normalized) space.
    Filters out components smaller than min_area.
    """
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        binary, connectivity=8
    )
    rects = []
    for i in range(1, num_labels):  # skip background (label 0)
        x = int(stats[i, cv2.CC_STAT_LEFT])
        y = int(stats[i, cv2.CC_STAT_TOP])
        w = int(stats[i, cv2.CC_STAT_WIDTH])
        h = int(stats[i, cv2.CC_STAT_HEIGHT])
        area = float(stats[i, cv2.CC_STAT_AREA])
        if area >= min_area:
            rects.append((x, y, w, h))
    return rects


# ── LINE EXTRACTION ───────────────────────────────────────────────────────────


def detect_visual_lines(
    cv_image: np.ndarray,
    trace: CoordinateTransformTrace,
    page_width: int,
    page_height: int,
    min_length_inches: float = 0.5,
) -> List[DetectedLine]:
    """
    Extract horizontal and vertical lines via morphology+contours pipeline.

    Pipeline (mandatory order per spec):
        1. Adaptive Threshold
        2. Morphology (horizontal kernel / vertical kernel)
        3. Connected Components + Contour Cleanup
        4. Contour bounding-rect → line coordinates
        5. Hough Refinement (optional post-filter for angle correction)

    All coordinates are projected back to PAGE_PIXELS immediately.
    """
    gray = _to_grayscale(cv_image)
    thresh = _adaptive_threshold(gray)

    min_length_px_normalized = int(TARGET_DPI * min_length_inches)
    lines_out: List[DetectedLine] = []

    # ── HORIZONTAL LINES ─────────────────────────────────────────────────────
    # Kernel: wide × 1 → isolates horizontal ink runs
    h_kernel_w = max(30, int(TARGET_DPI // 4))
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (h_kernel_w, 1))
    horizontal_mask = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, h_kernel, iterations=2)
    horizontal_mask = cleanup_contours(horizontal_mask, min_area=20.0)

    cnts, _ = cv2.findContours(
        horizontal_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        if w < min_length_px_normalized:
            continue
        # Project back to PAGE_PIXELS
        nx1, ny1, nx2, ny2 = trace.project_bbox_back(x, y, x + w, y + h)
        thickness_px = (ny2 - ny1)  # already in page_pixels
        cy = (ny1 + ny2) / 2.0  # center y as canonical line position
        lines_out.append(DetectedLine(
            x1=nx1, y1=cy, x2=nx2, y2=cy,
            orientation="horizontal",
            thickness=max(1.0, thickness_px),
            confidence=1.0,
            trace=trace,
        ))

    # ── VERTICAL LINES ───────────────────────────────────────────────────────
    v_kernel_h = max(30, int(TARGET_DPI // 4))
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, v_kernel_h))
    vertical_mask = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, v_kernel, iterations=2)
    vertical_mask = cleanup_contours(vertical_mask, min_area=20.0)

    cnts, _ = cv2.findContours(
        vertical_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        if h < min_length_px_normalized:
            continue
        nx1, ny1, nx2, ny2 = trace.project_bbox_back(x, y, x + w, y + h)
        thickness_px = (nx2 - nx1)
        cx = (nx1 + nx2) / 2.0
        lines_out.append(DetectedLine(
            x1=cx, y1=ny1, x2=cx, y2=ny2,
            orientation="vertical",
            thickness=max(1.0, thickness_px),
            confidence=1.0,
            trace=trace,
        ))

    logger.info(
        f"detect_visual_lines: {sum(1 for l in lines_out if l.orientation=='horizontal')} "
        f"horizontal, {sum(1 for l in lines_out if l.orientation=='vertical')} vertical"
    )
    return lines_out


# ── CHECKBOX DETECTION ────────────────────────────────────────────────────────


def detect_checkbox_regions(
    cv_image: np.ndarray,
    trace: CoordinateTransformTrace,
    page_width: int,
    page_height: int,
    min_size_px: int = 12,
    max_size_px: Optional[int] = None,
) -> List[DetectedBox]:
    """
    Multi-signal checkbox detection with mandatory anti-false-positive filters.

    Positive signals:
      - Shape score (quadrilateral approximation)
      - Fill ratio (outline only, not solid)
      - Size normalization (relative to TARGET_DPI)
      - Aspect ratio (square-ish)
      - Extent (compactness)

    Anti-false-positive constraints (all must pass):
      - Reject elongated rectangles (aspect_ratio > 1.4)
      - Reject very large boxes (probably input_boxes, not checkboxes)
      - Reject solid-filled regions (fill_ratio > 0.45)
      - Reject logo-region candidates (very large area)
      - Reject contours connected to long line structures
    """
    if max_size_px is None:
        max_size_px = int(TARGET_DPI * 0.55)  # ~0.55 inch max

    gray = _to_grayscale(cv_image)
    thresh = _adaptive_threshold(gray)

    # Close broken checkbox boundaries (small gaps in outline)
    close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, close_kernel, iterations=1)

    # RETR_CCOMP: retrieve both outer and inner contours
    cnts, hierarchy = cv2.findContours(
        closed, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE
    )

    # Build a set of contours that are part of long line structures
    # (Anti-FP: reject boxes that are actually horizontal/vertical rules)
    long_line_mask = _build_long_line_mask(thresh)

    boxes_out: List[DetectedBox] = []

    for i, c in enumerate(cnts):
        peri = cv2.arcLength(c, True)
        if peri < 4:
            continue
        approx = cv2.approxPolyDP(c, 0.04 * peri, True)

        # POSITIVE: quadrilateral shape
        if len(approx) < 4 or len(approx) > 6:
            continue

        x, y, w, h = cv2.boundingRect(approx)

        # ANTI-FP 1: size filter
        if w < min_size_px or h < min_size_px:
            continue
        if w > max_size_px or h > max_size_px:
            continue

        # ANTI-FP 2: aspect ratio (must be square-ish)
        aspect = float(w) / float(h)
        if aspect < 0.70 or aspect > 1.43:
            continue

        # POSITIVE: shape score (area vs perimeter → circularity-like metric for squares)
        area = cv2.contourArea(c)
        bbox_area = float(w * h)
        if bbox_area == 0:
            continue
        extent = area / bbox_area
        shape_score = min(1.0, extent * 1.2)  # tight-fitting quads score near 1.0

        # ANTI-FP 3: extent (not collapsed/degenerate)
        if extent < 0.55:
            continue

        # POSITIVE: fill ratio (checkbox outline = low fill)
        roi = thresh[y:y+h, x:x+w]
        if roi.size == 0:
            continue
        white_px = int(cv2.countNonZero(roi))
        fill_ratio = white_px / float(roi.size)

        # ANTI-FP 4: reject solid blobs and nearly empty noise
        if fill_ratio < 0.04 or fill_ratio > 0.48:
            continue

        # ANTI-FP 5: reject if centroid overlaps with long line structure
        cx_box = x + w // 2
        cy_box = y + h // 2
        if _point_on_long_line(long_line_mask, cx_box, cy_box, margin=5):
            continue

        # Project back to PAGE_PIXELS
        nx1, ny1, nx2, ny2 = trace.project_bbox_back(
            float(x), float(y), float(x + w), float(y + h)
        )

        bbox = BoundingBox(
            x1=nx1, y1=ny1, x2=nx2, y2=ny2,
            coordinate_space=CoordinateSpace.PAGE_PIXELS,
            page_width=page_width,
            page_height=page_height,
        )
        confidence = min(1.0, shape_score * (1.0 - abs(fill_ratio - 0.18) * 2))
        boxes_out.append(DetectedBox(
            bbox=bbox,
            box_type="checkbox",
            confidence=confidence,
            fill_ratio=fill_ratio,
            shape_score=shape_score,
            trace=trace,
        ))

    logger.info(f"detect_checkbox_regions: {len(boxes_out)} checkbox candidates found")
    return boxes_out


def _build_long_line_mask(thresh: np.ndarray) -> np.ndarray:
    """
    Build a binary mask of long line structures to reject false-positive
    checkboxes that are actually part of table separators.
    Threshold for 'long': at least 60px at 300dpi (~0.2 inch).
    """
    min_line_len = max(40, int(TARGET_DPI * 0.2))

    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (min_line_len, 1))
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, min_line_len))

    h_mask = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, h_kernel)
    v_mask = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, v_kernel)

    return cv2.bitwise_or(h_mask, v_mask)


def _point_on_long_line(
    long_line_mask: np.ndarray,
    cx: int, cy: int,
    margin: int = 5,
) -> bool:
    """Return True if the point (cx, cy) lies on or near a long line structure."""
    h, w = long_line_mask.shape
    x0 = max(0, cx - margin)
    y0 = max(0, cy - margin)
    x1 = min(w, cx + margin)
    y1 = min(h, cy + margin)
    roi = long_line_mask[y0:y1, x0:x1]
    return bool(cv2.countNonZero(roi) > 0)


# ── GENERIC BOX DETECTION ─────────────────────────────────────────────────────


def detect_boxes(
    cv_image: np.ndarray,
    trace: CoordinateTransformTrace,
    page_width: int,
    page_height: int,
) -> List[DetectedBox]:
    """
    Detect all rectangular regions: checkboxes, input boxes, signature boxes,
    table cells, and image regions.

    Calls detect_checkbox_regions for small squares.
    Uses contour hierarchy for larger rectangles (input_box, signature_box).
    """
    boxes: List[DetectedBox] = []

    # 1. Checkboxes (small squares)
    checkboxes = detect_checkbox_regions(
        cv_image, trace, page_width, page_height,
    )
    boxes.extend(checkboxes)

    # 2. Larger rectangular regions (input boxes, signature areas)
    larger = _detect_large_rectangles(cv_image, trace, page_width, page_height)
    boxes.extend(larger)

    logger.info(
        f"detect_boxes: {len(checkboxes)} checkboxes + "
        f"{len(larger)} large rects = {len(boxes)} total"
    )
    return boxes


def _detect_large_rectangles(
    cv_image: np.ndarray,
    trace: CoordinateTransformTrace,
    page_width: int,
    page_height: int,
) -> List[DetectedBox]:
    """
    Detect input boxes, signature areas, and image regions.
    Min size: larger than a checkbox (> 0.55 inch at 300 DPI).
    """
    gray = _to_grayscale(cv_image)
    thresh = _adaptive_threshold(gray)

    close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, close_kernel, iterations=2)

    cnts, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    min_dim = int(TARGET_DPI * 0.55)  # > checkbox threshold
    max_fraction = 0.7  # skip near-full-page boxes (page border noise)
    img_h, img_w = cv_image.shape[:2]

    rects: List[DetectedBox] = []
    for c in cnts:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.03 * peri, True)
        if len(approx) < 4 or len(approx) > 8:
            continue

        x, y, w, h = cv2.boundingRect(approx)
        if w < min_dim or h < min_dim:
            continue
        if w > img_w * max_fraction or h > img_h * max_fraction:
            continue

        aspect = float(w) / float(h)
        area = cv2.contourArea(c)
        bbox_area = float(w * h)
        if bbox_area == 0:
            continue
        fill_ratio = float(cv2.countNonZero(thresh[y:y+h, x:x+w])) / bbox_area

        # Classify by aspect ratio and fill
        if aspect > 3.0:
            box_type = "input_box"
        elif aspect > 0.5 and fill_ratio < 0.2:
            box_type = "signature_box" if w > TARGET_DPI * 1.5 else "input_box"
        else:
            box_type = "image_region"

        nx1, ny1, nx2, ny2 = trace.project_bbox_back(
            float(x), float(y), float(x + w), float(y + h)
        )
        bbox = BoundingBox(
            x1=nx1, y1=ny1, x2=nx2, y2=ny2,
            coordinate_space=CoordinateSpace.PAGE_PIXELS,
            page_width=page_width,
            page_height=page_height,
        )
        rects.append(DetectedBox(
            bbox=bbox,
            box_type=box_type,
            confidence=0.75,
            fill_ratio=fill_ratio,
            shape_score=0.8,
            trace=trace,
        ))

    return rects
