"""
core/quarantine_gate.py — Emthethal AI
Structure-Aware Quarantine Layer.

QUARANTINE GATE:
- Rejects or quarantines data failing confidence, structure, or bbox checks
"""

import logging
from typing import List, Optional

from ..ingestion_models.schemas import (
    DocumentOutput,
    QuarantineConfig,
    QuarantineResult,
)

logger = logging.getLogger(__name__)

class QuarantineGate:
    """
    Strict validation gate that runs AFTER Pydantic validation.

    Checks:
    1. Average structure confidence >= threshold
    2. StructureBlocks are valid and non-empty
    3. Mandatory bounding boxes present for PDF outputs
    4. Empty cell ratio within bounds
    """

    def __init__(self, config: Optional[QuarantineConfig] = None):
        self.config = config or QuarantineConfig()

    def evaluate(self, doc: DocumentOutput) -> QuarantineResult:
        """
        Run all quarantine checks. Returns a QuarantineResult with
        pass/fail status and list of violations.
        """
        violations: List[str] = []
        avg_conf = doc.avg_confidence

        # Check 1: Average confidence threshold
        if avg_conf < self.config.min_avg_confidence:
            violations.append(
                f"Average confidence {avg_conf:.3f} below threshold "
                f"{self.config.min_avg_confidence}"
            )

        # Check 2: Valid, non-empty StructureBlocks
        all_blocks = [b for p in doc.pages for b in p.blocks]
        if not all_blocks:
            violations.append("No StructureBlocks found in document")

        for page in doc.pages:
            for block_idx, block in enumerate(page.blocks):
                if not block.rows:
                    violations.append(
                        f"Page {page.page_number}, Block {block_idx}: "
                        f"Empty StructureBlock (no rows)"
                    )

        # Check 3: Mandatory bbox for PDF outputs
        if doc.file_type == "pdf" and self.config.require_bbox_for_pdf:
            missing_bbox_count = 0
            total_cells = 0
            for page in doc.pages:
                for block in page.blocks:
                    for row in block.rows:
                        for cell in row.cells:
                            total_cells += 1
                            if cell.bbox is None:
                                missing_bbox_count += 1

            if total_cells > 0 and missing_bbox_count == total_cells:
                violations.append(
                    f"PDF output has no bounding boxes on any cell "
                    f"({missing_bbox_count}/{total_cells} cells missing bbox)"
                )

        # Check 4: Empty cell ratio
        total_cells = 0
        empty_cells = 0
        for page in doc.pages:
            for block in page.blocks:
                for row in block.rows:
                    for cell in row.cells:
                        total_cells += 1
                        if not cell.text.strip():
                            empty_cells += 1

        if total_cells > 0:
            empty_ratio = empty_cells / total_cells
            if empty_ratio > self.config.max_empty_cell_ratio:
                violations.append(
                    f"Empty cell ratio {empty_ratio:.2f} exceeds threshold "
                    f"{self.config.max_empty_cell_ratio}"
                )

        # Determine status
        if not violations:
            status = "pass"
            passed = True
            quarantine_flag = False
        elif len(violations) == 1 and avg_conf >= (self.config.min_avg_confidence * 0.8):
            status = "warning"
            passed = True  # Allow with warning
            quarantine_flag = False
        else:
            status = "hard_stop"
            passed = False
            quarantine_flag = True

        result = QuarantineResult(
            passed=passed,
            status=status,
            violations=violations,
            avg_confidence=round(avg_conf, 4),
            quarantine_flag=quarantine_flag,
        )

        if violations:
            logger.warning(
                f"Quarantine gate: status={status}, "
                f"violations={len(violations)}: {violations}"
            )
        else:
            logger.info(
                f"Quarantine gate: PASSED (confidence={avg_conf:.3f})"
            )

        return result

quarantine_gate = QuarantineGate()
