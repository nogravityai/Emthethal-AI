from typing import Protocol, runtime_checkable
import logging

from app.services.pipeline.pipeline_models import PipelineArtifact
from app.services.pipeline.pipeline_context import PipelineContext
from app.services.pipeline.artifact_store import ArtifactStore

logger = logging.getLogger(__name__)

@runtime_checkable
class PipelineStage(Protocol):
    """
    Strict contract for all pipeline stages.
    Stages must declare their requirements and strictly return an Artifact.
    """
    stage_name: str
    required_artifact_types: list[str]
    output_artifact_type: str

    def run(self, context: PipelineContext, store: ArtifactStore) -> PipelineArtifact:
        ...

class StageRunner:
    """
    Executes a PipelineStage safely, ensuring contracts are met.
    """
    def __init__(self, store: ArtifactStore):
        self.store = store

    def execute(self, stage: PipelineStage, context: PipelineContext) -> PipelineArtifact:
        logger.info(f"--- Running Pipeline Stage: {stage.stage_name} ---")
        
        # 1. Verify dependencies
        for req in stage.required_artifact_types:
            ref_id = context.artifact_references.get(req)
            if not ref_id or not self.store.get(ref_id):
                raise RuntimeError(f"Stage {stage.stage_name} missing required artifact: {req}")
                
        # 2. Run stage
        output_artifact = stage.run(context, self.store)
        
        # 3. Validate output
        if not isinstance(output_artifact, PipelineArtifact):
            raise TypeError(f"Stage {stage.stage_name} violated contract: did not return PipelineArtifact.")
            
        if output_artifact.artifact_type != stage.output_artifact_type:
            raise ValueError(f"Stage returned wrong artifact type. Expected {stage.output_artifact_type}, got {output_artifact.artifact_type}")
            
        # 4. Save and Register
        self.store.save(output_artifact)
        context.register_artifact(output_artifact.artifact_type, output_artifact.artifact_id)
        
        logger.info(f"Stage {stage.stage_name} complete. Produced: {output_artifact.artifact_id}")
        return output_artifact
