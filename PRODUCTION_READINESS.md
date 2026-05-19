# CFIS-P3-STABLE: Production Readiness Checklist

This document formalizes the production characteristics and operational constraints of the **Deterministic Evidence-Oriented Document Operating System**. It defines the guarantees, failure domains, and governance policies required before enterprise deployment.

## 1. Determinism Guarantees

The core value of CFIS is that exactly the same inputs (or modified evidence) yield exactly the same outputs without side effects.

- **Stable Identification**: Every token, region, edge, and field receives an SHA-256 hash `stable_id` generated purely from its intrinsic properties (coordinates, text, provenance lineage). UUIDs are banned for evidence nodes.
- **Replay Consistency**: A pipeline replay (`hitl/rerun`) executing identical artifacts + a predefined `OperationsLedger` is guaranteed to traverse the identical fusion graph and output mathematically identical `ResolvedFields`.
- **Immutable Artifacts**: Pipeline stages read `ArtifactStore` objects without mutation. Output is always a *new* artifact layer with incremented provenance depth.

## 2. Failure Domains

When edge cases inevitably occur in production, they fail gracefully according to the following domains:

- **OCR Corruption (Garbage Text)**: Caught by `ConfidenceEngine` as low `text_score`. Isolated to specific `SpatialRegionEvidence` and exported with low confidence, avoiding full-page rejection.
- **Geometry Drift (Spatial Shifts)**: Detected by `DriftDetectionEngine`. A structural score `> 0.45` is flagged as `catastrophic_drift`. The template `correction_reuse` engine will refuse to auto-suggest operations, failing open for human review.
- **Orphan Explosion (No Regions Detected)**: `OrphanRecoveryEngine` activates, attempting text-based bounding box extrapolation. If `anchor_penalty` exceeds thresholds, the document defaults to a pure-text hierarchy.
- **Replay Mismatch**: If an underlying codebase update breaks the deterministic graph, the `PipelineOrchestrator` detects missing derived artifacts and aborts replay, preventing silent data corruption.

## 3. Audit Guarantees

Every data point in the system survives legal/compliance audits.

- **"Why does this field exist?"**: Answered via `ResolvedFieldProvenance`, tracing directly back to explicit `alignment_edges` and `human_operations`.
- **"Who modified the evidence?"**: Managed via `OperationsLedger`. The system records `operator_id`, `action_type`, and `target_evidence_ids` in an append-only structure. The final `CanonicalSchema` maintains a `provenance_ref` back to this ledger.
- **"When did the replay occur?"**: Captured at the Orchestrator level via `PipelineContext.execution_timestamp`. Each rerun generates a new `run_id` linked to the `rerun_of_id`.

## 4. Operational Limits

To ensure system stability, the following physical and logical bounds are enforced:

- **Max Pages per Run**: Currently tested for up to 50 pages. Processing beyond this limit should chunk processing or use a paginated queue.
- **Memory Assumptions**: A single run context holds ~5MB of JSON evidence graph artifacts. 
- **Replay Cost**: Replay skips OCR and Geometry stages (O(1) retrieval). Time complexity is bottlenecked purely by `FusionEngine` graph resolution (O(N) for N regions).
- **Artifact Retention**: `ArtifactStore` currently resides in-memory. For enterprise scale, a Redis/PostgreSQL backend eviction policy must be implemented (e.g., retain artifacts for 7 days, retain CanonicalSchema indefinitely).

## 5. Security & Governance

- **Ledger Immutability**: `OperationsLedger` entries cannot be deleted or modified. "Undoing" an operation requires appending an inverse operation.
- **Operator Identity**: All HITL operations must carry an authenticated `operator_id` (enforced via JWT/IAM at the gateway).
- **Export Controls**: Adapters (e.g., `FormioAdapter`) strictly consume the `CanonicalDocument` schema, isolating consumer applications from underlying PII or sensitive geometric logic.

---
**ARCHITECTURE_VERSION = CFIS-P3-STABLE**
*System is locked for evolution management. Any changes to Graph or Alignment logic mandate a bump in pipeline_version.*
