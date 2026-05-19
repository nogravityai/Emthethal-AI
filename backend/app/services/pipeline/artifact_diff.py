from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

class DiffIssue(BaseModel):
    category: str  # "structural", "confidence", "provenance", "spatial", "orphan"
    path: str
    expected: Any
    actual: Any
    message: str

class ArtifactDiffReport(BaseModel):
    is_identical: bool
    issues: List[DiffIssue] = []

def diff_artifacts(expected_payload: Any, actual_payload: Any) -> ArtifactDiffReport:
    """
    Intelligent artifact differ. 
    Does not just do 'actual == expected'. Computes deltas and structural mismatches.
    """
    issues = []
    
    # Simple list handling
    if isinstance(expected_payload, list) and isinstance(actual_payload, list):
        if len(expected_payload) != len(actual_payload):
            issues.append(DiffIssue(
                category="structural",
                path="list_length",
                expected=len(expected_payload),
                actual=len(actual_payload),
                message="Length mismatch in artifact list."
            ))
            
        # Try to match by stable ID or index
        for i, (exp, act) in enumerate(zip(expected_payload, actual_payload)):
            _diff_objects(exp, act, f"[{i}]", issues)
            
    elif isinstance(expected_payload, dict) and isinstance(actual_payload, dict):
        _diff_dicts(expected_payload, actual_payload, "root", issues)
    else:
        # Fallback to direct attribute diff
        _diff_objects(expected_payload, actual_payload, "root", issues)

    return ArtifactDiffReport(is_identical=(len(issues) == 0), issues=issues)

def _diff_objects(exp: Any, act: Any, path: str, issues: List[DiffIssue]):
    if type(exp) != type(act):
        issues.append(DiffIssue(category="structural", path=path, expected=str(type(exp)), actual=str(type(act)), message="Type mismatch"))
        return
        
    if hasattr(exp, "__dict__"):
        for k, v_exp in exp.__dict__.items():
            if k.startswith("_"): continue
            v_act = getattr(act, k, None)
            
            # Specialized Diffs
            if k == "confidence_breakdown":
                _diff_confidence(v_exp, v_act, f"{path}.{k}", issues)
            elif k == "provenance":
                _diff_provenance(v_exp, v_act, f"{path}.{k}", issues)
            elif k == "bbox":
                _diff_spatial(v_exp, v_act, f"{path}.{k}", issues)
            elif isinstance(v_exp, (str, int, float, bool, list, dict)):
                if v_exp != v_act:
                    # Treat orphans specifically
                    cat = "orphan" if k == "orphaned" else "structural"
                    issues.append(DiffIssue(category=cat, path=f"{path}.{k}", expected=v_exp, actual=v_act, message="Value mismatch"))
            else:
                _diff_objects(v_exp, v_act, f"{path}.{k}", issues)
    elif exp != act:
        issues.append(DiffIssue(category="structural", path=path, expected=exp, actual=act, message="Value mismatch"))

def _diff_confidence(exp: Any, act: Any, path: str, issues: List[DiffIssue]):
    if exp is None or act is None:
        if exp != act: issues.append(DiffIssue("confidence", path, exp, act, "Missing confidence breakdown"))
        return
        
    for metric in ["geometry_score", "assignment_score", "text_score", "final_score"]:
        e_val = getattr(exp, metric, 0.0)
        a_val = getattr(act, metric, 0.0)
        if abs(e_val - a_val) > 0.01: # Small tolerance
            issues.append(DiffIssue(category="confidence", path=f"{path}.{metric}", expected=e_val, actual=a_val, message="Confidence delta exceeded tolerance"))

def _diff_provenance(exp: Any, act: Any, path: str, issues: List[DiffIssue]):
    # Just checking if source module and evidence types match. 
    # Can expand to trace full lineage.
    if hasattr(exp, "source_module") and hasattr(act, "source_module"):
        if exp.source_module != act.source_module:
            issues.append(DiffIssue(category="provenance", path=f"{path}.source_module", expected=exp.source_module, actual=act.source_module, message="Provenance broken"))

def _diff_spatial(exp: Any, act: Any, path: str, issues: List[DiffIssue]):
    if exp is None or act is None:
        if exp != act: issues.append(DiffIssue("spatial", path, exp, act, "Missing bbox"))
        return
    for coord in ["x1", "y1", "x2", "y2"]:
        e_val = getattr(exp, coord, 0)
        a_val = getattr(act, coord, 0)
        if abs(e_val - a_val) > 1.0: # 1px tolerance
            issues.append(DiffIssue("spatial", f"{path}.{coord}", e_val, a_val, "Spatial coordinate drift"))
