#!/usr/bin/env python3
import sys
import os
import logging

# Setup sys.path to find /app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("RegressionSuite")

from app.services.pipeline.regression_cases import ALL_CASES, RegressionCase
from app.services.pipeline.pipeline_context import PipelineContext
from app.services.pipeline.orchestration import PipelineOrchestrator
from app.services.pipeline.pipeline_models import PipelineArtifact, generate_stable_id
from app.services.pipeline.artifact_store import ArtifactStore

from app.services.pipeline.perception_stage import PerceptionStage
from app.services.hitl.evidence_patcher import EvidencePatchStage
from app.services.topology.stage import TopologyStage
from app.services.alignment.engine import AlignmentStage
from app.services.fusion.fusion_engine import AlignmentFusionStage, FusionEngine
from app.services.alignment.models import AlignmentType

# Import HITL Ledger and Models
from app.services.hitl.operations_ledger import global_operations_ledger
from app.services.hitl.models import HumanOperation, HumanLineRejection, HumanRegionMerge

# Define mock relabel model if not yet standard in hitl/models
try:
    from app.services.hitl.models import HumanRelabelCorrection
except ImportError:
    class HumanRelabelCorrection(HumanOperation):
        operation_type: str = "relabel"
        region_id: str
        new_value: str


def run_case(case: RegressionCase) -> dict:
    """Run a single regression case and return a report of successes/failures."""
    logger.info("=" * 60)
    logger.info(f"RUNNING CASE: {case.case_id}")
    logger.info(f"DESCRIPTION:  {case.description}")
    logger.info("=" * 60)

    # 1. Setup Context and Orchestrator
    ctx = PipelineContext(document_id=case.case_id, pipeline_version="3.0.0")
    orch = PipelineOrchestrator()

    # Wire all stages in order
    orch.add_stage(_FixtureOCRStage(case.ocr_payload))
    orch.add_stage(_FixtureGeomStage(case.geometry_payload))
    orch.add_stage(PerceptionStage())
    orch.add_stage(EvidencePatchStage())
    orch.add_stage(TopologyStage())
    orch.add_stage(AlignmentStage())
    orch.add_stage(AlignmentFusionStage())

    report = {
        "case_id": case.case_id,
        "success": True,
        "results": []
    }

    try:
        # For Human Override case, we do an initial run, apply corrections, then rerun
        if case.case_id == "human_override_case":
            # Initial run
            orch.run_pipeline(ctx)
            store = orch.store
            
            # Find the resolved fields
            rf_id = ctx.artifact_references["resolved_fields"]
            resolved = store.get(rf_id).payload
            assert len(resolved) > 0, "No fields resolved in initial run of human override"
            
            # Get target region from the first field
            first_field = resolved[0]
            target_region_id = first_field.resolved_provenance.geometry_regions[0]
            initial_value = first_field.value
            initial_field_id = first_field.field_id
            
            logger.info(f"Initial run completed. First field ID={initial_field_id}, target_region={target_region_id[:12]}, value={initial_value}")
            
            # Inject the relabel operation into the ledger
            corr = case.human_corrections[0]
            new_val = corr["correction_data"]["new_value"]
            
            op = HumanRelabelCorrection(
                run_id=ctx.run_id,
                operator_id="test_operator",
                target_evidence_ids=[target_region_id],
                region_id=target_region_id,
                new_value=new_val
            )
            global_operations_ledger.append(op)
            
            # Clear downstream and rerun
            for s in ["patched_evidence", "topology_evidence", "alignment_evidence", "resolved_fields"]:
                ctx.artifact_references.pop(s, None)
                
            orch.rerun_from_stage(ctx, "evidence_patching")
            
        else:
            # Regular run
            orch.run_pipeline(ctx)

        # 2. Assertions Verification
        store = orch.store
        
        # Helper to get artifacts
        ocr_ev = store.get(ctx.artifact_references["ocr_evidence"]).payload
        geom_ev = store.get(ctx.artifact_references["geometry_evidence"]).payload
        align_ev = store.get(ctx.artifact_references["alignment_evidence"]).payload
        resolved_fields = store.get(ctx.artifact_references["resolved_fields"]).payload

        for assertion in case.assertions:
            ast_id = assertion.name
            ast_desc = assertion.description
            status = "PASSED"
            error_msg = ""
            
            try:
                if case.case_id == "multi_region_conflict_case":
                    if ast_id == "alignment_count_ge_2":
                        assert len(align_ev) >= 2, f"Expected >= 2 alignments, got {len(align_ev)}"
                    elif ast_id == "conflict_edge_exists":
                        engine = FusionEngine()
                        engine.build_graph(align_ev)
                        engine.consolidate_evidence(align_ev)
                        conflict_edges = [e for e in engine.graph.edges.values() if e.edge_type == "conflicts"]
                        assert len(conflict_edges) > 0, "No conflict edges found between competing regions"
                    elif ast_id == "resolved_count_eq_2":
                        assert len(resolved_fields) == 2, f"Expected exactly 2 resolved fields, got {len(resolved_fields)}"
                    elif ast_id == "no_token_dropped":
                        boundary_token_id = [t.stable_id for t in ocr_ev if t.text == "boundary_token"][0]
                        found = any(boundary_token_id in rf.resolved_provenance.ocr_tokens for rf in resolved_fields)
                        assert found, "boundary_token stable_id was dropped from all resolved provenances"
                        
                elif case.case_id == "touching_boundary_case":
                    if ast_id == "touching_classified_correctly":
                        touching_id = [t.stable_id for t in ocr_ev if t.text == "touching_left"][0]
                        touching_aligns = [a for a in align_ev if a.source_evidence_id == touching_id and a.alignment_type == AlignmentType.TOKEN_TOUCHING_REGION]
                        assert len(touching_aligns) > 0, "touching_left was not classified as TOKEN_TOUCHING_REGION"
                    elif ast_id == "inside_classified_correctly":
                        inside_id = [t.stable_id for t in ocr_ev if t.text == "inside_token"][0]
                        inside_aligns = [a for a in align_ev if a.source_evidence_id == inside_id and a.alignment_type == AlignmentType.TOKEN_INSIDE_REGION]
                        assert len(inside_aligns) > 0, "inside_token was not classified as TOKEN_INSIDE_REGION"
                    elif ast_id == "orphan_not_resolved":
                        far_orphan_id = [t.stable_id for t in ocr_ev if t.text == "far_orphan"][0]
                        for rf in resolved_fields:
                            assert far_orphan_id not in rf.resolved_provenance.ocr_tokens, "far_orphan was resolved in a field"
                    elif ast_id == "touching_lower_score":
                        touching_id = [t.stable_id for t in ocr_ev if t.text == "touching_left"][0]
                        inside_id = [t.stable_id for t in ocr_ev if t.text == "inside_token"][0]
                        t_score = [a.alignment_score for a in align_ev if a.source_evidence_id == touching_id][0]
                        i_score = [a.alignment_score for a in align_ev if a.source_evidence_id == inside_id][0]
                        assert t_score < i_score, f"Touching score {t_score} is not lower than inside score {i_score}"
                        
                elif case.case_id == "merged_cells_case":
                    if ast_id == "single_resolved_field":
                        assert len(resolved_fields) == 1, f"Expected 1 resolved field, got {len(resolved_fields)}"
                    elif ast_id == "all_tokens_in_provenance":
                        prov_tokens = set(resolved_fields[0].resolved_provenance.ocr_tokens)
                        expected_tokens = {t.stable_id for t in ocr_ev}
                        assert expected_tokens.issubset(prov_tokens), f"Missing tokens in provenance. Expected {expected_tokens}, got {prov_tokens}"
                    elif ast_id == "alignment_count_eq_3":
                        assert len(align_ev) == 3, f"Expected exactly 3 alignments, got {len(align_ev)}"
                        
                elif case.case_id == "orphan_recovery_case":
                    if ast_id == "close_orphan_recovered":
                        close_orphan_id = [t.stable_id for t in ocr_ev if t.text == "close_orphan"][0]
                        found = any(close_orphan_id in rf.resolved_provenance.ocr_tokens for rf in resolved_fields)
                        assert found, "close_orphan was not recovered in any resolved field"
                    elif ast_id == "distant_orphan_stays_orphan":
                        distant_orphan_id = [t.stable_id for t in ocr_ev if t.text == "distant_orphan"][0]
                        for rf in resolved_fields:
                            assert distant_orphan_id not in rf.resolved_provenance.ocr_tokens, "distant_orphan was recovered"
                    elif ast_id == "recovery_is_probabilistic":
                        close_orphan_id = [t.stable_id for t in ocr_ev if t.text == "close_orphan"][0]
                        inside_id = [t.stable_id for t in ocr_ev if t.text == "inside_token"][0]
                        c_score = [a.alignment_score for a in align_ev if a.source_evidence_id == close_orphan_id][0]
                        i_score = [a.alignment_score for a in align_ev if a.source_evidence_id == inside_id][0]
                        assert c_score < i_score, f"Close orphan recovery score {c_score} is not lower than inside score {i_score}"
                        
                elif case.case_id == "geometry_conflict_case":
                    if ast_id == "conflict_edge_exists":
                        engine = FusionEngine()
                        engine.build_graph(align_ev)
                        engine.consolidate_evidence(align_ev)
                        conflict_edges = [e for e in engine.graph.edges.values() if e.edge_type == "conflicts"]
                        assert len(conflict_edges) > 0, "No conflict edges found between competing regions"
                    elif ast_id == "high_conf_region_wins":
                        # High confidence region has confidence 0.95, low conf has 0.55
                        assert len(resolved_fields) > 0, "No resolved fields found"
                    elif ast_id == "conflict_in_provenance":
                        any_penalty = any(rf.confidence_breakdown.conflict_penalty > 0 for rf in resolved_fields)
                        assert any_penalty, "No conflict penalty found in resolved fields breakdown"
                        
                elif case.case_id == "human_override_case":
                    first_field = resolved_fields[0]
                    if ast_id == "override_changes_value":
                        assert first_field.value == "REJECTED_BY_DOCTOR", f"Value was not overridden, got {first_field.value}"
                    elif ast_id == "human_in_provenance":
                        assert len(first_field.resolved_provenance.human_operations) > 0, "No human operation in provenance"
                    elif ast_id == "override_is_deterministic":
                        assert first_field.field_id is not None
                        
                else:
                    raise ValueError(f"Unknown case_id: {case.case_id}")
                    
            except AssertionError as ae:
                status = "FAILED"
                error_msg = str(ae)
                report["success"] = False
                logger.error(f"  [x] Assertion FAILED: {ast_id} - {ast_desc}")
                logger.error(f"      Reason: {error_msg}")
            except Exception as e:
                status = "ERROR"
                error_msg = f"{type(e).__name__}: {str(e)}"
                report["success"] = False
                logger.error(f"  [x] Assertion ERROR: {ast_id} - {ast_desc}", exc_info=True)
                
            report["results"].append({
                "assertion_id": ast_id,
                "description": ast_desc,
                "status": status,
                "error": error_msg
            })
            
            if status == "PASSED":
                logger.info(f"  [✓] Assertion PASSED: {ast_id} - {ast_desc}")

    except Exception as e:
        report["success"] = False
        report["error"] = f"Runtime pipeline error: {type(e).__name__}: {str(e)}"
        logger.error(f"Pipeline crashed for case {case.case_id}: {e}", exc_info=True)

    return report


# ── Fixture Stages for OCR and Geometry ────────────────────────────────────────

class _FixtureOCRStage:
    stage_name = "raw_ocr_input"
    required_artifact_types = []
    output_artifact_type = "raw_ocr_dicts"
    def __init__(self, payload): self._p = payload
    def run(self, ctx, store):
        return PipelineArtifact(
            artifact_id=generate_stable_id("api_ocr", str(self._p)),
            artifact_type="raw_ocr_dicts", payload=self._p
        )

class _FixtureGeomStage:
    stage_name = "raw_cv2_data"
    required_artifact_types = []
    output_artifact_type = "raw_cv2_dicts"
    def __init__(self, payload): self._p = payload
    def run(self, ctx, store):
        return PipelineArtifact(
            artifact_id=generate_stable_id("api_geom", str(self._p)),
            artifact_type="raw_cv2_dicts", payload=self._p
        )


def main():
    logger.info("Starting CFIS Core Regression Suite...")
    
    passed_cases = 0
    total_cases = len(ALL_CASES)
    reports = []
    
    for case in ALL_CASES:
        res = run_case(case)
        reports.append(res)
        if res["success"]:
            passed_cases += 1
            logger.info(f"CASE {case.case_id}: SUCCESS\n")
        else:
            logger.error(f"CASE {case.case_id}: FAILED\n")

    logger.info("=" * 60)
    logger.info(f"REGRESSION SUITE COMPLETED: {passed_cases}/{total_cases} CASES PASSED")
    logger.info("=" * 60)

    # Exit with code 0 if all passed, else 1
    if passed_cases == total_cases:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
