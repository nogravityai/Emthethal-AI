"""
TASK-P3-12B — Audited Operations Ledger

Append-only immutable event log for human operations.
"""
from typing import List, Dict, Optional
import json
import logging
import threading

from app.services.hitl.models import HumanOperation

logger = logging.getLogger(__name__)


class OperationsLedger:
    """
    In-memory ledger for the current execution cycle.
    In production, this translates to an append-only PostgreSQL table or Event Store.
    """
    def __init__(self):
        self._operations: List[HumanOperation] = []
        self._lock = threading.Lock()

    def append(self, operation: HumanOperation) -> str:
        """Append an operation to the ledger. Immutable once appended."""
        with self._lock:
            # Enforce immutability
            for existing in self._operations:
                if existing.operation_id == operation.operation_id:
                    raise ValueError(f"Operation {operation.operation_id} already exists in the ledger.")
            
            self._operations.append(operation)
            logger.info(f"Ledger: appended {operation.operation_type} by {operation.operator_id} for run {operation.run_id}")
            return operation.operation_id

    def get_operations_for_run(self, run_id: str) -> List[HumanOperation]:
        """Fetch all operations applied to a specific pipeline run."""
        with self._lock:
            return [op for op in self._operations if op.run_id == run_id]

    def get_all_operations(self) -> List[HumanOperation]:
        """Fetch the entire ledger."""
        with self._lock:
            return list(self._operations)


# Global in-memory singleton for the current phase.
global_operations_ledger = OperationsLedger()
