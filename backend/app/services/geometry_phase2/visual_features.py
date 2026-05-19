# ============================================================
# CFIS Phase 2 — Visual Features (geometry_phase2 package entry point)
# Location: backend/app/services/geometry_phase2/visual_features.py
#
# This module delegates to the canonical visual_geometry.py service.
# It exists as an entry point within the geometry_phase2 package
# and re-exports the primary pipeline functions for convenience.
#
# CANONICAL IMPLEMENTATION:
#   backend/app/services/visual_geometry.py
# ============================================================

from app.services.geometry.visual_geometry import (
    normalize_image_dpi,
    detect_visual_lines,
    detect_boxes,
    detect_checkbox_regions,
    extract_connected_components,
    cleanup_contours,
    DetectedLine,
    DetectedBox,
    TARGET_DPI,
)
from app.services.coordinate_trace import CoordinateTransformTrace

__all__ = [
    "normalize_image_dpi",
    "detect_visual_lines",
    "detect_boxes",
    "detect_checkbox_regions",
    "extract_connected_components",
    "cleanup_contours",
    "DetectedLine",
    "DetectedBox",
    "CoordinateTransformTrace",
    "TARGET_DPI",
]
