import uuid
from typing import Dict, Any, List
from pydantic import BaseModel, Field

class PipelineContext(BaseModel):
    """
    Lightweight runtime context. 
    DOES NOT hold data payloads, giant graphs, or raw images.
    Only metadata, references, and configurations.
    """
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    document_id: str
    pipeline_version: str = "3.0.0"
    
    # Global configs (e.g., skip_ocr, hitl_mode)
    configuration: Dict[str, Any] = Field(default_factory=dict)
    
    # Mapping of artifact_type -> artifact_id
    # Stages use this to locate their required inputs from the ArtifactStore
    artifact_references: Dict[str, str] = Field(default_factory=dict)
    
    def register_artifact(self, artifact_type: str, artifact_id: str):
        self.artifact_references[artifact_type] = artifact_id
