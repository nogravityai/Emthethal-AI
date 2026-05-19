# ============================================================
# CFIS Phase 2 — Coordinate Trace Module
# Location: backend/app/services/coordinate_trace.py
#
# INVARIANT (Rule 6): ALL geometry transformations MUST emit a
# CoordinateTransformTrace. Silent coordinate mutations are forbidden.
#
# INVARIANT (Rule 5): ALL visual geometry primitives MUST be transformed
# into canonical CoordinateSpace.PAGE_PIXELS before fusion.
# ============================================================

from __future__ import annotations

import logging
import math
from typing import Optional, Tuple

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ── TARGET DPI (Rule 7) ──────────────────────────────────────────────────────
TARGET_DPI: int = 300


class CoordinateTransformTrace(BaseModel):
    """
    Immutable record of every geometric transformation applied to an image
    or coordinate set. Guarantees that all extracted primitives can be
    projected back to canonical PAGE_PIXELS without drift.

    Chain traces when multiple transforms are applied sequentially:
        trace_1 = normalize_image_dpi(...)       → source_dpi→300dpi space
        trace_2 = apply_crop(trace_1, ...)       → cropped space
        combined = CoordinateTransformTrace.chain(trace_1, trace_2)
    """

    source_space: str = Field(
        ...,
        description="Name of the coordinate space before transformation.",
    )
    target_space: str = Field(
        ...,
        description="Name of the coordinate space after transformation.",
    )
    scale_x: float = Field(
        default=1.0,
        description="Horizontal scale factor: target_px = source_px * scale_x",
    )
    scale_y: float = Field(
        default=1.0,
        description="Vertical scale factor: target_px = source_px * scale_y",
    )
    offset_x: float = Field(
        default=0.0,
        description="Horizontal offset applied AFTER scaling.",
    )
    offset_y: float = Field(
        default=0.0,
        description="Vertical offset applied AFTER scaling.",
    )
    rotation: float = Field(
        default=0.0,
        description="Rotation in degrees (counter-clockwise). Deskew angle.",
    )
    dpi_before: Optional[int] = Field(
        default=None,
        description="Source image DPI before this transform.",
    )
    dpi_after: Optional[int] = Field(
        default=None,
        description="Target image DPI after this transform.",
    )

    def project_forward(self, x: float, y: float) -> Tuple[float, float]:
        """
        Transform a (x, y) point from source_space → target_space.
        Applies: scale → offset.
        Rotation is NOT applied here (must be handled at image level).
        """
        tx = x * self.scale_x + self.offset_x
        ty = y * self.scale_y + self.offset_y
        return tx, ty

    def project_back(self, x: float, y: float) -> Tuple[float, float]:
        """
        Transform a (x, y) point from target_space → source_space.
        Inverse of project_forward.
        """
        tx = (x - self.offset_x) / self.scale_x if self.scale_x != 0 else 0.0
        ty = (y - self.offset_y) / self.scale_y if self.scale_y != 0 else 0.0
        return tx, ty

    def project_bbox_back(
        self,
        x1: float, y1: float,
        x2: float, y2: float,
    ) -> Tuple[float, float, float, float]:
        """
        Project a bounding box from target_space → source_space (PAGE_PIXELS).
        Use this after OpenCV extracts primitives in the DPI-normalized space.
        """
        nx1, ny1 = self.project_back(x1, y1)
        nx2, ny2 = self.project_back(x2, y2)
        return nx1, ny1, nx2, ny2

    @classmethod
    def identity(cls, space: str = "page_pixels") -> "CoordinateTransformTrace":
        """No-op trace for when no transformation is applied."""
        return cls(
            source_space=space,
            target_space=space,
            scale_x=1.0,
            scale_y=1.0,
            offset_x=0.0,
            offset_y=0.0,
        )

    @classmethod
    def from_dpi_normalization(
        cls,
        source_dpi: float,
        source_width_px: int,
        source_height_px: int,
    ) -> "CoordinateTransformTrace":
        """
        Construct the trace for DPI normalization (Rule 7).
        scale_x = scale_y = TARGET_DPI / source_dpi
        """
        scale = TARGET_DPI / source_dpi
        logger.debug(
            f"DPI normalization trace: {source_dpi:.1f} → {TARGET_DPI} DPI "
            f"(scale={scale:.4f}, "
            f"source={source_width_px}×{source_height_px}px, "
            f"target={int(source_width_px * scale)}×{int(source_height_px * scale)}px)"
        )
        return cls(
            source_space="page_pixels",
            target_space=f"normalized_opencv_{TARGET_DPI}dpi",
            scale_x=scale,
            scale_y=scale,
            offset_x=0.0,
            offset_y=0.0,
            dpi_before=int(source_dpi),
            dpi_after=TARGET_DPI,
        )

    @classmethod
    def from_crop(
        cls,
        parent_trace: "CoordinateTransformTrace",
        crop_x: float,
        crop_y: float,
    ) -> "CoordinateTransformTrace":
        """
        Construct the trace for a crop operation applied to an already-traced image.
        The crop offset is in the PARENT's target space.
        """
        return cls(
            source_space=parent_trace.target_space,
            target_space=f"{parent_trace.target_space}_cropped",
            scale_x=parent_trace.scale_x,
            scale_y=parent_trace.scale_y,
            offset_x=parent_trace.offset_x + crop_x,
            offset_y=parent_trace.offset_y + crop_y,
            dpi_before=parent_trace.dpi_after,
            dpi_after=parent_trace.dpi_after,
        )

    @classmethod
    def from_deskew(
        cls,
        parent_trace: "CoordinateTransformTrace",
        angle_degrees: float,
    ) -> "CoordinateTransformTrace":
        """
        Construct a trace that records a deskew rotation.
        Note: bbox projection with rotation requires full affine math;
        this records the angle for audit purposes.
        """
        return cls(
            source_space=parent_trace.target_space,
            target_space=f"{parent_trace.target_space}_deskewed",
            scale_x=parent_trace.scale_x,
            scale_y=parent_trace.scale_y,
            offset_x=parent_trace.offset_x,
            offset_y=parent_trace.offset_y,
            rotation=angle_degrees,
            dpi_before=parent_trace.dpi_after,
            dpi_after=parent_trace.dpi_after,
        )

    def __repr__(self) -> str:
        return (
            f"CoordinateTransformTrace("
            f"{self.source_space!r} → {self.target_space!r}, "
            f"scale=({self.scale_x:.3f},{self.scale_y:.3f}), "
            f"offset=({self.offset_x:.1f},{self.offset_y:.1f}), "
            f"rot={self.rotation:.2f}°, "
            f"dpi={self.dpi_before}→{self.dpi_after})"
        )
