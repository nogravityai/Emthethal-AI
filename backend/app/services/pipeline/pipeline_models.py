from typing import Any, Dict, List, Optional
import hashlib
from datetime import datetime, timezone
from pydantic import BaseModel, Field

def generate_stable_id(*args) -> str:
    """
    Generates a deterministic ID based on the input arguments.
    Crucial for replayability and regression diffing. No random UUIDs.
    """
    m = hashlib.sha256()
    for arg in args:
        m.update(str(arg).encode('utf-8'))
    return m.hexdigest()

class PipelineArtifact(BaseModel):
    """
    Immutable envelope for data moving between stages.
    Stages DO NOT consume or produce raw models, they consume/produce Artifacts.
    """
    artifact_id: str
    artifact_type: str  # e.g., 'ocr_tokens', 'layout_hypotheses', 'evidence_graph'
    schema_version: str = "3.0.0"
    pipeline_version: str = "3.0.0"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    derived_from: List[str] = Field(default_factory=list) # Parent artifact IDs
    
    # The actual payload (immutable)
    payload: Any
    
    class Config:
        frozen = True # Enforce immutability at the Pydantic level
