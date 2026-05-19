# ============================================================
# CFIS Phase 2 — Primitives (Canonical Re-exports)
# Location: backend/app/services/geometry_phase2/primitives.py
#
# This file re-exports the authoritative types from the canonical
# Phase 2 service modules to maintain backward compatibility
# with internal geometry_phase2 package imports.
#
# CANONICAL LOCATIONS:
#   coordinate_trace.py  → CoordinateTransformTrace
#   visual_geometry.py   → DetectedLine, DetectedBox
#   structural_analysis.py → StructuralAnchor, SpatialRegion
#   hypothesis_engine.py → LayoutHypothesis, GeometryEvidence
# ============================================================

from app.services.coordinate_trace import CoordinateTransformTrace
from app.services.geometry.visual_geometry import DetectedLine, DetectedBox
from app.services.spatial.structural_analysis import StructuralAnchor, SpatialRegion
from app.services.fusion.hypothesis_engine import LayoutHypothesis, GeometryEvidence

__all__ = [
    "CoordinateTransformTrace",
    "DetectedLine",
    "DetectedBox",
    "StructuralAnchor",
    "SpatialRegion",
    "LayoutHypothesis",
    "GeometryEvidence",
]
