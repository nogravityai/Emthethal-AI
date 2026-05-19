"""
TASK-P3-13B — Drift Detection Engine

Measures structural divergence between an incoming document and a known template fingerprint.
Returns a drift_score between 0.0 (identical structure) and 1.0 (completely different).
"""
import math
from app.services.templates.template_fingerprint import TemplateFingerprint

def calculate_drift_score(fp_a: TemplateFingerprint, fp_b: TemplateFingerprint) -> float:
    """
    Calculates the drift between two fingerprints.
    Accounts for region count divergence and spatial density divergence.
    """
    if fp_a.region_count == 0 and fp_b.region_count == 0:
        return 0.0
    if fp_a.region_count == 0 or fp_b.region_count == 0:
        return 1.0
        
    # 1. Region Count Drift
    count_diff = abs(fp_a.region_count - fp_b.region_count)
    max_count = max(fp_a.region_count, fp_b.region_count)
    count_drift = count_diff / max_count
    
    # 2. Aspect Ratio Drift
    aspect_drift = abs(fp_a.aspect_ratio - fp_b.aspect_ratio) / max(fp_a.aspect_ratio, fp_b.aspect_ratio)
    
    # 3. Spatial Density Drift (Earth Mover's Distance approximation / Cell overlap)
    a_cells = fp_a.grid_density.cells
    b_cells = fp_b.grid_density.cells
    
    all_keys = set(a_cells.keys()).union(set(b_cells.keys()))
    
    total_divergence = 0
    total_regions = max_count
    
    for k in all_keys:
        a_val = a_cells.get(k, 0)
        b_val = b_cells.get(k, 0)
        total_divergence += abs(a_val - b_val)
        
    density_drift = min(1.0, total_divergence / (total_regions * 2))
    
    # Weighted final score
    final_score = (count_drift * 0.4) + (aspect_drift * 0.1) + (density_drift * 0.5)
    
    return min(1.0, max(0.0, final_score))

def classify_drift(drift_score: float) -> str:
    if drift_score < 0.05:
        return "identical"
    elif drift_score < 0.20:
        return "minor_drift"
    elif drift_score < 0.45:
        return "moderate_drift"
    else:
        return "catastrophic_drift"
