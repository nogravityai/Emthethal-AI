import logging
from typing import List, Callable

from app.services.pipeline.pipeline_context import PipelineContext
from app.services.pipeline.artifact_store import ArtifactStore
from app.services.pipeline.stage_runner import StageRunner, PipelineStage
from app.services.pipeline.pipeline_models import PipelineArtifact

logger = logging.getLogger(__name__)

class PipelineOrchestrator:
    """
    Manages the deterministic execution flow of the document compiler.
    Supports observable event hooks (e.g., for Debug renders) without polluting stages.
    """
    def __init__(self):
        self.store = ArtifactStore()
        self.runner = StageRunner(self.store)
        self.stages: List[PipelineStage] = []
        self.observers: List[Callable[[PipelineArtifact, PipelineContext], None]] = []

    def add_stage(self, stage: PipelineStage):
        self.stages.append(stage)
        
    def add_observer(self, observer_fn: Callable[[PipelineArtifact, PipelineContext], None]):
        """Register an observer (e.g., Debug overlay generator) to run after each stage."""
        self.observers.append(observer_fn)

    def run_pipeline(self, context: PipelineContext) -> PipelineContext:
        """Execute all stages sequentially."""
        logger.info(f"Starting Document Compiler Pipeline for Run ID: {context.run_id}")
        
        for stage in self.stages:
            artifact = self.runner.execute(stage, context)
            
            # Notify observers (Debug snapshots are generated here!)
            for observer in self.observers:
                try:
                    observer(artifact, context)
                except Exception as e:
                    logger.error(f"Observer failed after stage {stage.stage_name}: {e}")
                    # Observers must not crash the main pipeline
                    
        logger.info("Pipeline execution completed successfully.")
        return context

    def rerun_from_stage(self, context: PipelineContext, start_stage_name: str):
        """
        Replayability feature: Resume pipeline from a specific stage
        using artifacts already present in the context/store.
        """
        logger.info(f"Re-running pipeline from stage: {start_stage_name}")
        
        start_idx = -1
        for i, stage in enumerate(self.stages):
            if stage.stage_name == start_stage_name:
                start_idx = i
                break
                
        if start_idx == -1:
            raise ValueError(f"Stage {start_stage_name} not found in pipeline.")
            
        for stage in self.stages[start_idx:]:
            self.runner.execute(stage, context)
            
        return context
