# Findings: Hierarchical Form Compiler Runtime (v5.2-PRODUCTION-SEALED)

## Discoveries & Context
- The user has Docker Desktop running but the volume mount or WSL environment setup might prevent correct syncing if we rebuild the entire set of containers from scratch (especially downloading pip packages again).
- We have the entire v5.2 specification in `Plan52.txt` and summarized in the prompt.
- The model definitions and backend logic need to be added/updated in the `backend/` project structure.
- In the next turns, we will implement the models, logic, and run tests.

## API Behavior & System Constraints
- Python 3.10 is used in backend.
- Pydantic v2 is used (`pydantic==2.6.4`).
- Pydantic models must use Pydantic v2 syntax (e.g. `BaseModel`, `Field(default_factory=...)`, `model_validator` instead of `root_validator`).
