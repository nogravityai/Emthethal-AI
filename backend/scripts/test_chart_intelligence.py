#!/usr/bin/env python3
"""
Test script for the Universal Chart Intelligence Subsystem contracts and models.
"""

import sys
import os
from datetime import datetime

# Setup sys.path to find /app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.schemas import BoundingBox, CoordinateSpace
from app.services.fusion.models import EvidenceProvenance
from app.core.contracts.evidence_contracts import (
    ISpatialEvidence,
    ITemporalEvidence,
    SpatialEvidenceContract,
    TemporalEvidenceContract
)
from app.core.charts.models import (
    AxisCalibration,
    ChartCoordinateSystem,
    ShapeEmbedding,
    TemporalPointEvidence
)


def test_contracts():
    print("Testing Evidence Contracts...")
    
    # 1. Setup sample bounding box and provenance
    bbox_pixel = BoundingBox(
        x1=10.0, y1=10.0, x2=50.0, y2=50.0,
        coordinate_space=CoordinateSpace.PAGE_PIXELS,
        page_width=1000, page_height=1000
    )
    
    prov = EvidenceProvenance(
        source_module="test_module",
        evidence_type="test_evidence",
        confidence_contribution=0.9
    )
    
    # 2. Test spatial evidence contract validation pass
    spatial_valid = SpatialEvidenceContract(
        stable_id="spatial_1",
        bbox=bbox_pixel,
        page_number=0,
        coordinate_space=CoordinateSpace.PAGE_PIXELS
    )
    print("  [✓] SpatialEvidenceContract valid serialization/validation passed")
    
    # 3. Test spatial evidence contract validation fail (mismatch coordinate space)
    bbox_norm = BoundingBox(
        x1=0.1, y1=0.1, x2=0.5, y2=0.5,
        coordinate_space=CoordinateSpace.NORMALIZED,
        page_width=1000, page_height=1000
    )
    try:
        SpatialEvidenceContract(
            stable_id="spatial_2",
            bbox=bbox_norm,
            page_number=0,
            coordinate_space=CoordinateSpace.PAGE_PIXELS
        )
        assert False, "Expected ValueError due to coordinate space mismatch"
    except ValueError as e:
        print(f"  [✓] SpatialEvidenceContract correctly rejected coordinate space mismatch: {e}")

    # 4. Test temporal evidence contract validation pass
    temporal_valid = TemporalEvidenceContract(
        stable_id="temporal_1",
        timestamp=120.5,
        provenance=prov
    )
    print("  [✓] TemporalEvidenceContract valid elapsed time passed")
    
    # 5. Test temporal evidence contract validation fail (negative elapsed time)
    try:
        TemporalEvidenceContract(
            stable_id="temporal_2",
            timestamp=-5.0,
            provenance=prov
        )
        assert False, "Expected ValueError due to negative timestamp"
    except ValueError as e:
        print(f"  [✓] TemporalEvidenceContract correctly rejected negative timestamp: {e}")


def test_coordinate_system():
    print("Testing ChartCoordinateSystem...")
    
    bbox = BoundingBox(
        x1=100.0, y1=100.0, x2=600.0, y2=600.0,
        coordinate_space=CoordinateSpace.PAGE_PIXELS,
        page_width=1000, page_height=1000
    )
    
    # Setup X axis: pixel 100 to 600 corresponds to 0.0 to 10.0 seconds
    x_cal = AxisCalibration(
        min_pixel=100.0, max_pixel=600.0,
        min_value=0.0, max_value=10.0
    )
    
    # Setup Y axis: pixel 600 (bottom) to 100 (top) corresponds to 50.0 to 150.0 heart rate (Pulse)
    # y = 600 -> Pulse = 50
    # y = 100 -> Pulse = 150
    y_cal = AxisCalibration(
        min_pixel=600.0, max_pixel=100.0,
        min_value=50.0, max_value=150.0
    )
    
    chart_sys = ChartCoordinateSystem(
        stable_id="chart_1",
        bbox=bbox,
        x_axis=x_cal,
        y_axis=y_cal,
        page_number=1
    )
    
    # Conversion checks
    # x = 350 (midpoint) -> 5.0 seconds
    # y = 350 (midpoint) -> 100.0 heart rate
    x_val, y_val = chart_sys.pixel_to_real(350.0, 350.0)
    assert abs(x_val - 5.0) < 1e-5, f"Expected 5.0, got {x_val}"
    assert abs(y_val - 100.0) < 1e-5, f"Expected 100.0, got {y_val}"
    print("  [✓] pixel_to_real conversion correct")
    
    # Reverse conversion checks
    px, py = chart_sys.real_to_pixel(5.0, 100.0)
    assert abs(px - 350.0) < 1e-5, f"Expected 350.0, got {px}"
    assert abs(py - 350.0) < 1e-5, f"Expected 350.0, got {py}"
    print("  [✓] real_to_pixel conversion correct")


def test_shape_embedding():
    print("Testing ShapeEmbedding...")
    
    # Create two embeddings with similar moments
    emb1 = ShapeEmbedding(
        hu_moments=[0.2083, 0.0156, 0.0, 0.0, 0.0, 0.0, 0.0],
        area=100.0,
        perimeter=40.0,
        aspect_ratio=2.0,
        centroid=(200.0, 200.0)
    )
    
    # Perfect match moments
    emb2 = ShapeEmbedding(
        hu_moments=[0.2083, 0.0156, 0.0, 0.0, 0.0, 0.0, 0.0],
        area=200.0,
        perimeter=80.0,
        aspect_ratio=2.0,
        centroid=(400.0, 400.0)
    )
    
    sim = emb1.match_similarity(emb2)
    assert abs(sim - 1.0) < 1e-3, f"Expected near 1.0 similarity for identical normalized shape, got {sim}"
    print(f"  [✓] Shape matching similarity for identical shape: {sim:.4f}")
    
    # Mismatched shape
    emb3 = ShapeEmbedding(
        hu_moments=[0.4, 0.2, 0.01, 0.02, 0.0, 0.0, 0.0],
        area=100.0,
        perimeter=40.0,
        aspect_ratio=1.0,
        centroid=(200.0, 200.0)
    )
    
    sim_diff = emb1.match_similarity(emb3)
    assert sim_diff < 0.9, f"Expected lower similarity for different shapes, got {sim_diff}"
    print(f"  [✓] Shape matching similarity for different shape: {sim_diff:.4f}")


def test_temporal_point_evidence():
    print("Testing TemporalPointEvidence Protocol compliance...")
    
    bbox = BoundingBox(
        x1=100.0, y1=100.0, x2=200.0, y2=200.0,
        coordinate_space=CoordinateSpace.PAGE_PIXELS,
        page_width=1000, page_height=1000
    )
    
    prov = EvidenceProvenance(
        source_module="chart_module",
        evidence_type="point_detection",
        confidence_contribution=0.95
    )
    
    point = TemporalPointEvidence(
        stable_id="point_1",
        bbox=bbox,
        page_number=1,
        coordinate_space=CoordinateSpace.PAGE_PIXELS,
        timestamp=45.2,
        value=112.5,
        value_label="heart_rate",
        provenance=prov
    )
    
    # Protocol check
    assert isinstance(point, ISpatialEvidence)
    assert isinstance(point, ITemporalEvidence)
    print("  [✓] TemporalPointEvidence implements ISpatialEvidence and ITemporalEvidence protocols successfully")


def main():
    print("=" * 60)
    print("RUNNING CHART INTELLIGENCE SUBSYSTEM UNIT TESTS")
    print("=" * 60)
    
    try:
        test_contracts()
        test_coordinate_system()
        test_shape_embedding()
        test_temporal_point_evidence()
        print("=" * 60)
        print("ALL TESTS PASSED SUCCESSFULLY!")
        print("=" * 60)
        sys.exit(0)
    except Exception as e:
        print(f"\n[x] TEST SUITE CRASHED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
