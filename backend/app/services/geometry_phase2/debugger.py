# ============================================================
# CFIS Phase 2 — Debugger (geometry_phase2 package entry point)
# Location: backend/app/services/geometry_phase2/debugger.py
#
# Delegates to the canonical geometry_debugger.py service.
# ============================================================

from app.services.debug.geometry_debugger import (
    GeometryDebugSnapshot,
    render_geometry_debug,
    render_hypothesis_overlay,
    render_grid_graph,
    render_anchor_overlay,
    snapshot_to_dict,
)

__all__ = [
    "GeometryDebugSnapshot",
    "render_geometry_debug",
    "render_hypothesis_overlay",
    "render_grid_graph",
    "render_anchor_overlay",
    "snapshot_to_dict",
]
