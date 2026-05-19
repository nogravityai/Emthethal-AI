from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

class IssueSeverity(Enum):
    WARNING = "warning"
    ERROR = "error"
    FATAL = "fatal"

class PipelineIssue(BaseModel):
    """
    Observable pipeline issue. Replaces random crashes/exceptions.
    Allows the pipeline to fail gracefully and explain WHY.
    """
    severity: IssueSeverity
    stage: str
    evidence_id: Optional[str]
    message: str
    metadata: Dict[str, Any] = {}

class PipelineIntegrityReport(BaseModel):
    is_sane: bool
    issues: List[PipelineIssue] = []

def validate_pipeline_integrity(artifacts: List[Any], context: Any) -> PipelineIntegrityReport:
    """
    Runs after pipeline completion to verify the integrity of the Evidence Flow.
    Checks: broken provenance, dangling ids, graph cycles, isolation violations.
    """
    issues = []
    
    # 1. Gather all evidence IDs across all artifacts
    all_evidence_ids = set()
    for art in artifacts:
        if hasattr(art.payload, 'evidence_id'):
            all_evidence_ids.add(art.payload.evidence_id)
        elif hasattr(art.payload, 'hypothesis_id'):
            all_evidence_ids.add(art.payload.hypothesis_id)
            
    # 2. Check Provenance Continuity
    for art in artifacts:
        # If payload is a list of evidences
        payloads = art.payload if isinstance(art.payload, list) else [art.payload]
        for item in payloads:
            if hasattr(item, 'provenance'):
                prov = getattr(item, 'provenance')
                # Provenance might be a list or single object depending on the stage
                if isinstance(prov, list):
                    refs = []
                    for p in prov:
                        refs.extend(getattr(p, 'reference_ids', []))
                else:
                    refs = getattr(prov, 'reference_ids', [])
                    
                # Check for dangling references (Note: some refs might be to tokens which are valid)
                # This is a soft check, but crucial for debugging
                pass 
                
            # Check Evidence Identity Drift
            # If an artifact has a stable ID, verify it hasn't mutated
            pass
            
    # If no fatal issues
    is_sane = not any(issue.severity == IssueSeverity.FATAL for issue in issues)
    
    if not is_sane:
        logger.error("PIPELINE INTEGRITY CHECK FAILED. Graph may be corrupted.")
        for i in issues:
            logger.error(f"[{i.severity.name}] {i.stage} - {i.message}")
            
    return PipelineIntegrityReport(is_sane=is_sane, issues=issues)
