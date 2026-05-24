# Backward-compatibility thin wrapper
from app.core.geometry.visual_geometry import (
    DetectedLine,
    DetectedBox,
    normalize_image_dpi,
    cleanup_contours,
    extract_connected_components,
    detect_visual_lines,
    detect_checkbox_regions,
    detect_boxes,
)
