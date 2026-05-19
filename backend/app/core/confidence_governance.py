"""
core/confidence_governance.py — Emthethal AI
=============================================
Gap #4: AI Confidence Governance Policy

Provides a deterministic, policy-driven routing decision based on
the average OCR/extraction confidence score of a processed document.

Thresholds (configurable via environment or DB settings):

  avg_confidence >= AUTO_PASS_THRESHOLD  → QA_PENDING (auto-queued, low friction)
  avg_confidence >= QA_REVIEW_THRESHOLD  → QA_PENDING  (human review mandatory)
  avg_confidence < QA_REVIEW_THRESHOLD   → QUARANTINED (blocked until triaged)

Why thresholds matter:
  Without this, the QA queue becomes either:
  - always full (everything goes to review) → QA fatigue
  - always empty (everything auto-passes)   → quality risk
  A policy layer makes the system consistent and auditable.

Rule: FastAPI reads this policy.
"""

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ── Outcome ────────────────────────────────────────────────────────────────────

class ConfidenceOutcome(str, Enum):
    AUTO_PASS   = "AUTO_PASS"    # High confidence → minimal friction QA
    QA_REVIEW   = "QA_REVIEW"   # Medium confidence → mandatory human review
    QUARANTINE  = "QUARANTINE"  # Low confidence   → blocked, needs triage


# ── Policy ────────────────────────────────────────────────────────────────────

@dataclass
class ConfidencePolicy:
    """
    Thresholds loaded from environment variables or defaults.
    Adjust per deployment without code changes.
    """
    # Above this: form goes to QA queue with "auto-approved" recommendation
    auto_pass_threshold: float = field(
        default_factory=lambda: float(os.getenv("CONFIDENCE_AUTO_PASS", "0.90"))
    )
    # Between this and auto_pass: mandatory human QA review
    qa_review_threshold: float = field(
        default_factory=lambda: float(os.getenv("CONFIDENCE_QA_REVIEW", "0.70"))
    )
    # Below qa_review_threshold: quarantine

    def validate(self) -> None:
        if not (0.0 < self.qa_review_threshold < self.auto_pass_threshold <= 1.0):
            raise ValueError(
                f"Invalid thresholds: qa_review={self.qa_review_threshold}, "
                f"auto_pass={self.auto_pass_threshold}. "
                f"Must satisfy: 0 < qa_review < auto_pass <= 1"
            )


# ── Governance Result ─────────────────────────────────────────────────────────

@dataclass
class GovernanceResult:
    outcome: ConfidenceOutcome
    avg_confidence: float
    recommendation: str          # Human-readable explanation
    auto_approve_suggested: bool
    requires_human_review: bool
    metadata: Dict[str, Any]


# ── Evaluator ─────────────────────────────────────────────────────────────────

class ConfidenceGovernor:
    """
    Stateless evaluator. Takes a confidence score, returns a routing decision.
    One instance per application lifecycle (singleton).
    """

    def __init__(self, policy: Optional[ConfidencePolicy] = None):
        self.policy = policy or ConfidencePolicy()
        self.policy.validate()
        logger.info(
            f"ConfidenceGovernor initialized: "
            f"auto_pass={self.policy.auto_pass_threshold}, "
            f"qa_review={self.policy.qa_review_threshold}"
        )

    def evaluate(
        self,
        avg_confidence: float,
        document_id: Optional[int] = None,
        form_title: Optional[str] = None,
    ) -> GovernanceResult:
        """
        Evaluate the confidence score and return a routing decision.

        Args:
            avg_confidence: Float between 0.0 and 1.0. Average across all
                            extracted blocks for this document.
            document_id:    For logging only.
            form_title:     For logging only.

        Returns:
            GovernanceResult with outcome and human-readable recommendation.
        """
        p = self.policy
        ctx = f"[doc={document_id}, form='{form_title}', conf={avg_confidence:.3f}]"

        if avg_confidence >= p.auto_pass_threshold:
            outcome = ConfidenceOutcome.AUTO_PASS
            recommendation = (
                f"Confidence {avg_confidence:.1%} ≥ {p.auto_pass_threshold:.1%} threshold. "
                f"High quality extraction. QA review recommended but may be waived."
            )
            auto_approve_suggested = True
            requires_human_review = False

        elif avg_confidence >= p.qa_review_threshold:
            outcome = ConfidenceOutcome.QA_REVIEW
            recommendation = (
                f"Confidence {avg_confidence:.1%} is between "
                f"{p.qa_review_threshold:.1%} and {p.auto_pass_threshold:.1%}. "
                f"Human QA review mandatory before deployment."
            )
            auto_approve_suggested = False
            requires_human_review = True

        else:
            outcome = ConfidenceOutcome.QUARANTINE
            recommendation = (
                f"Confidence {avg_confidence:.1%} < {p.qa_review_threshold:.1%} threshold. "
                f"Document quarantined. Manual triage required before QA review."
            )
            auto_approve_suggested = False
            requires_human_review = True

        logger.info(f"Confidence governance: {outcome.value} {ctx}")

        return GovernanceResult(
            outcome=outcome,
            avg_confidence=avg_confidence,
            recommendation=recommendation,
            auto_approve_suggested=auto_approve_suggested,
            requires_human_review=requires_human_review,
            metadata={
                "auto_pass_threshold": p.auto_pass_threshold,
                "qa_review_threshold": p.qa_review_threshold,
                "document_id":         document_id,
                "form_title":          form_title,
            },
        )

    def evaluate_from_blocks(
        self,
        confidences: list[float],
        document_id: Optional[int] = None,
        form_title: Optional[str] = None,
    ) -> GovernanceResult:
        """
        Convenience method: compute average from a list of block-level confidences.
        """
        if not confidences:
            logger.warning(f"No confidence scores provided for {document_id}. Quarantining.")
            return self.evaluate(0.0, document_id, form_title)

        avg = sum(confidences) / len(confidences)
        return self.evaluate(avg, document_id, form_title)


# ── Singleton ─────────────────────────────────────────────────────────────────
confidence_governor = ConfidenceGovernor()
