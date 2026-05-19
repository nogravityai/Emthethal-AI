"""
TASK-P3-10 — Golden Regression Cases

Six behavioral contracts for the Reasoning Engine.
Each case is a self-contained fixture: fixed inputs + declarative assertions.
No randomness. No external I/O. No inference calls.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class RegressionAssertion:
    name: str
    description: str

@dataclass
class RegressionCase:
    case_id: str
    description: str
    ocr_payload: Dict[str, Any]
    geometry_payload: Dict[str, Any]
    human_corrections: List[Dict[str, Any]]         # injected after first fusion pass
    assertions: List[RegressionAssertion]


def _base_meta(page_w=1000, page_h=1000):
    return {
        "opencv_version": "4.10.0", "kernel_signature": "morph_rect_3x3",
        "dpi_normalization": "identity", "thresholding_profile": "adaptive_gaussian",
        "original_space": "page_pixels", "page_width": page_w, "page_height": page_h
    }


# ── CASE 1 — Multi-Region Conflict ──────────────────────────────────────────

MULTI_REGION_CONFLICT = RegressionCase(
    case_id="multi_region_conflict_case",
    description="Token spans boundary between two adjacent regions. "
                "Expect TWO AlignmentEvidence, one ConflictEdge, ONE ResolvedField owner.",
    ocr_payload={
        "source_engine": "paddleocr", "engine_version": "2.6.0",
        "page_width": 1000, "page_height": 1000, "page_number": 1,
        "tokens": [
            # Sits on the boundary between reg_a (x=50-200) and reg_b (x=200-350)
            {"bbox": [180, 60, 220, 80], "text": "boundary_token", "confidence": 0.90, "space": "page_pixels"},
            # Clean token fully inside reg_a
            {"bbox": [55, 60, 150, 80], "text": "inside_a",      "confidence": 0.99, "space": "page_pixels"},
        ]
    },
    geometry_payload={
        "meta": _base_meta(),
        "lines": [],
        "boxes": [
            {"bbox": [50, 50, 200, 90], "confidence": 0.97},   # reg_a
            {"bbox": [200, 50, 350, 90], "confidence": 0.97},  # reg_b
        ]
    },
    human_corrections=[],
    assertions=[
        RegressionAssertion("alignment_count_ge_2", "boundary_token must produce at least 2 AlignmentEvidence"),
        RegressionAssertion("conflict_edge_exists", "A ConflictEdge must exist between the two alignment nodes"),
        RegressionAssertion("resolved_count_eq_2", "Exactly 2 ResolvedFields (one per region), not 3"),
        RegressionAssertion("no_token_dropped", "boundary_token stable_id appears in at least one provenance chain"),
    ]
)

# ── CASE 2 — Touching Boundary ───────────────────────────────────────────────

TOUCHING_BOUNDARY = RegressionCase(
    case_id="touching_boundary_case",
    description="Token touches region edge without overlapping. "
                "Must classify as TOKEN_TOUCHING_REGION, not INSIDE or CROSSES.",
    ocr_payload={
        "source_engine": "paddleocr", "engine_version": "2.6.0",
        "page_width": 1000, "page_height": 1000, "page_number": 1,
        "tokens": [
            # Ends exactly at region left edge x=50 with 4px gap → inside TOUCHING threshold (5px)
            {"bbox": [47, 60, 49, 80], "text": "touching_left",  "confidence": 0.88, "space": "page_pixels"},
            # Fully inside
            {"bbox": [60, 60, 150, 80], "text": "inside_token", "confidence": 0.99, "space": "page_pixels"},
            # Far away → orphan
            {"bbox": [700, 700, 800, 720], "text": "far_orphan", "confidence": 0.75, "space": "page_pixels"},
        ]
    },
    geometry_payload={
        "meta": _base_meta(),
        "lines": [],
        "boxes": [{"bbox": [50, 50, 250, 90], "confidence": 0.97}]
    },
    human_corrections=[],
    assertions=[
        RegressionAssertion("touching_classified_correctly", "touching_left must produce TOKEN_TOUCHING_REGION alignment"),
        RegressionAssertion("inside_classified_correctly",  "inside_token must produce TOKEN_INSIDE_REGION alignment"),
        RegressionAssertion("orphan_not_resolved",          "far_orphan must NOT appear in any ResolvedField provenance"),
        RegressionAssertion("touching_lower_score",         "touching alignment_score < inside alignment_score"),
    ]
)

# ── CASE 3 — Merged Cells (Rowspan) ──────────────────────────────────────────

MERGED_CELLS = RegressionCase(
    case_id="merged_cells_case",
    description="One large region contains multiple tokens (rowspan). "
                "All tokens preserved in one ResolvedField provenance, field not split.",
    ocr_payload={
        "source_engine": "paddleocr", "engine_version": "2.6.0",
        "page_width": 1000, "page_height": 1000, "page_number": 1,
        "tokens": [
            {"bbox": [55, 55, 150, 75],  "text": "Line 1", "confidence": 0.99, "space": "page_pixels"},
            {"bbox": [55, 80, 200, 100], "text": "Line 2", "confidence": 0.98, "space": "page_pixels"},
            {"bbox": [55, 105, 180, 125],"text": "Line 3", "confidence": 0.97, "space": "page_pixels"},
        ]
    },
    geometry_payload={
        "meta": _base_meta(),
        "lines": [],
        "boxes": [{"bbox": [50, 50, 250, 130], "confidence": 0.97}]  # one big merged cell
    },
    human_corrections=[],
    assertions=[
        RegressionAssertion("single_resolved_field",     "Exactly 1 ResolvedField produced (not 3)"),
        RegressionAssertion("all_tokens_in_provenance",  "All 3 token stable_ids appear in that field's provenance"),
        RegressionAssertion("alignment_count_eq_3",      "3 AlignmentEvidence items (one per token→region)"),
    ]
)

# ── CASE 4 — Orphan Recovery ──────────────────────────────────────────────────

ORPHAN_RECOVERY = RegressionCase(
    case_id="orphan_recovery_case",
    description="Two orphans: one close enough for recovery (nearest-region fallback), "
                "one too far to recover. Tests OrphanRecoveryPipeline probabilistic output.",
    ocr_payload={
        "source_engine": "paddleocr", "engine_version": "2.6.0",
        "page_width": 1000, "page_height": 1000, "page_number": 1,
        "tokens": [
            {"bbox": [55, 55, 200, 75],  "text": "inside_token",   "confidence": 0.99, "space": "page_pixels"},
            # Close orphan: 15px outside region boundary → should recover
            {"bbox": [265, 55, 320, 75], "text": "close_orphan",   "confidence": 0.85, "space": "page_pixels"},
            # Far orphan: 400px away → must stay orphan
            {"bbox": [700, 700, 800, 720],"text": "distant_orphan","confidence": 0.70, "space": "page_pixels"},
        ]
    },
    geometry_payload={
        "meta": _base_meta(),
        "lines": [],
        "boxes": [{"bbox": [50, 50, 250, 90], "confidence": 0.97}]
    },
    human_corrections=[],
    assertions=[
        RegressionAssertion("close_orphan_recovered",      "close_orphan must appear in some ResolvedField provenance"),
        RegressionAssertion("distant_orphan_stays_orphan", "distant_orphan must NOT appear in any ResolvedField"),
        RegressionAssertion("recovery_is_probabilistic",   "close_orphan alignment_score < inside_token alignment_score"),
    ]
)

# ── CASE 5 — Geometry vs Clustering Conflict ──────────────────────────────────

GEOMETRY_CONFLICT = RegressionCase(
    case_id="geometry_conflict_case",
    description="Legacy clustering says 'paragraph', visual geometry says 'table_cell'. "
                "ConflictEdge must exist. Fusion picks higher-confidence side. "
                "Provenance must show the conflict source.",
    ocr_payload={
        "source_engine": "paddleocr", "engine_version": "2.6.0",
        "page_width": 1000, "page_height": 1000, "page_number": 1,
        "tokens": [
            {"bbox": [55, 55, 240, 75], "text": "Patient Name:", "confidence": 0.99, "space": "page_pixels"},
            {"bbox": [245, 55, 445, 75], "text": "John Doe",     "confidence": 0.95, "space": "page_pixels"},
        ]
    },
    geometry_payload={
        "meta": _base_meta(),
        "lines": [],
        # Two competing regions: geometry_cell and a wider legacy paragraph region
        "boxes": [
            {"bbox": [50, 50, 250, 90],  "confidence": 0.95},  # geometry table_cell
            {"bbox": [50, 50, 450, 90],  "confidence": 0.55},  # legacy paragraph (lower conf)
        ]
    },
    human_corrections=[],
    assertions=[
        RegressionAssertion("conflict_edge_exists",         "ConflictEdge must exist between competing regions"),
        RegressionAssertion("high_conf_region_wins",        "ResolvedField references the high-confidence region"),
        RegressionAssertion("conflict_in_provenance",       "conflict_penalty > 0 in winning ResolvedField breakdown"),
    ]
)

# ── CASE 6 — Human Override ────────────────────────────────────────────────────

HUMAN_OVERRIDE = RegressionCase(
    case_id="human_override_case",
    description="After initial Fusion, a HITL correction injects HumanCorrectionEvidence. "
                "Re-fusion must produce a different (overridden) ResolvedField deterministically.",
    ocr_payload={
        "source_engine": "paddleocr", "engine_version": "2.6.0",
        "page_width": 1000, "page_height": 1000, "page_number": 1,
        "tokens": [
            {"bbox": [55, 55, 240, 75], "text": "Approved",   "confidence": 0.90, "space": "page_pixels"},
        ]
    },
    geometry_payload={
        "meta": _base_meta(),
        "lines": [],
        "boxes": [{"bbox": [50, 50, 250, 90], "confidence": 0.97}]
    },
    human_corrections=[
        {
            "action_type": "relabel",
            "correction_data": {"new_value": "REJECTED_BY_DOCTOR"},
            "target_field_idx": 0    # targets the first ResolvedField
        }
    ],
    assertions=[
        RegressionAssertion("override_changes_value",         "ResolvedField value changes after human correction"),
        RegressionAssertion("human_in_provenance",            "human_operations list is non-empty in corrected field"),
        RegressionAssertion("override_is_deterministic",      "Two reruns with same correction produce identical IDs"),
    ]
)

ALL_CASES = [
    MULTI_REGION_CONFLICT,
    TOUCHING_BOUNDARY,
    MERGED_CELLS,
    ORPHAN_RECOVERY,
    GEOMETRY_CONFLICT,
    HUMAN_OVERRIDE,
]
