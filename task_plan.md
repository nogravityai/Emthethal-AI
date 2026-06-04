# Task Plan: Hierarchical Form Compiler Runtime (v5.2-PRODUCTION-SEALED)

## Goal
Implement the CFIS Unified Core Hierarchical Form Compiler Runtime (v5.2-PRODUCTION-SEALED) as a robust, single-page atomic processing system, closing all gaps and passing all regression cases.

## Current Phase
Phase 1: Model Definition & Schema Migration

## Phases

### Phase 1: Model Definition & Schema Migration
- [x] Define all Pydantic models in `backend/app/core/forms/models.py` matching the CFIS v5.2 specification.
- [x] Define the PageMetadata, Provenance, DetectionMetadata, and VisualFeatures models.
- [x] Define error models: ProcessingError, SnapshotRaceConditionError, DeterminismViolationAlert.
- [x] Define base & concrete ledger operations: BaseLedgerOperation, ZoneOperation, FieldOperation, CompensateOperation, DraftOperation.
- [x] Define ReadingOrderEntry, ReadingOrderSequence, and ConstraintCondition.
- [x] Define ConstraintGraph, TemplateFailureLog, SemanticZoneProposal, FieldGroupCandidate, HierarchicalFieldPair.
- [x] Define SchemaMigrationAdapter and run the migration cli.
- **Status:** completed

### Phase 2: Core Algorithmic Engine Updates
- [x] Update LayoutGrammarEngine, ParentChildLinkerEngine, FieldTypeInferenceEngine, and CompositeFieldContainerEngine to support the new features.
- [x] Implement adaptive elastic snapping `snap_radius_px` formula and text aggregation `elastic_relaxation_buffer_px` formula.
- [x] Update ParentChildLinkerEngine to support HierarchicalFieldPair.
- [x] Implement Large Container Partitioning with RepeatedFieldPattern parsing.
- **Status:** completed

### Phase 3: Transactional Ledger & Concurrent HITL Operations
- [x] Implement optimistic locking using `lock_version` in LedgerOperationEngine.
- [x] Implement StateRefresh subscription mechanism in MacroHITLEditorEngine.
- [x] Set up the memory/JSON storage for PageStateStore and PageMutationEvent pub/sub.
- [x] Implement hot-reload protocol in ConstraintRegistry FileWatcher.
- **Status:** completed

### Phase 4: Integration, Testing & Verification
- [x] Wire the backend runtime components into a unified execution flow.
- [x] Write regression tests for v5.2 features.
- [x] Run the local regression suite and verify that all test cases pass.
- **Status:** completed

### Phase 5: Handoff & Session Close
- [x] Clean up files and verify zero regression.
- [x] Write final session summary.
- **Status:** completed

## Key Questions
1. Is it necessary to restart docker services? (No, we will execute tests locally or restart only specific services if needed, but the user requested not downloading libraries and stopped docker compose down).
2. What are the specific snapping and text aggregation formulas? (Snapping: `snap_radius_px = base_snap_px * (1.0 + confidence * scale_factor)`. Text aggregation: `elastic_relaxation_buffer_px = min(max_buffer_px, base_buffer_px * (1.0 + word_density * elastic_relaxation_multiplier_constant))`).

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Implement models in `backend/app/core/forms/models.py` | Centralizes all CFIS form compiler models in one clean file |
| Execute tests and verify backend code using a local runner or docker exec if possible | Ensures maximum fidelity with the running app |

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| None | 1 | N/A |
