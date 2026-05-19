from typing import Dict, Optional
from app.services.pipeline.pipeline_models import PipelineArtifact

class ArtifactStore:
    """
    In-memory or persistent store for PipelineArtifacts.
    In production, this could be backed by Redis or S3 for distributed execution and replay.
    """
    def __init__(self):
        self._store: Dict[str, PipelineArtifact] = {}
        
    def save(self, artifact: PipelineArtifact) -> None:
        """Store an artifact by its stable ID."""
        if artifact.artifact_id in self._store:
            # Idempotent save: if the exact ID exists, it means determinism holds.
            # We just return early instead of crashing.
            return
        self._store[artifact.artifact_id] = artifact
        
    def get(self, artifact_id: str) -> Optional[PipelineArtifact]:
        """Retrieve an artifact by its ID."""
        return self._store.get(artifact_id)
        
    def get_by_type(self, artifact_type: str) -> Optional[PipelineArtifact]:
        """Retrieve the latest artifact of a given type."""
        # For simplicity in linear pipelines:
        matches = [a for a in self._store.values() if a.artifact_type == artifact_type]
        if not matches:
            return None
        # Return the most recently created one
        return sorted(matches, key=lambda a: a.created_at, reverse=True)[0]
