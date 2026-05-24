from .visual_geometry import (
    DetectedLine,
    DetectedBox,
    detect_visual_lines,
    detect_checkbox_regions,
    detect_boxes,
)
from .border_inference import (
    BorderFragment,
    InferredBorderFragment,
    BorderInferenceResult,
    run_border_inference,
)
from .geometry_engine import (
    GeometryEngine,
    OCRWord,
    ReconstructedCell,
    ReconstructedTable,
    geometry_engine,
)
