"""
services/async_queue.py — Emthethal AI
=======================================
Gap #5: Async Pipeline / Queue Layer

Uses Redis + RQ (Redis Queue) for background task processing.
Minimal, Python-native, no broker complexity.

Pipeline flow (async):
  Upload → FastAPI → enqueue_job() → Redis Queue → Worker
  → OCR Worker → Geometry Worker → Canonical Generator
  → Confidence Governor → QA State Update

Why RQ over Celery:
  - Zero additional config files
  - Native async-friendly
  - Introspectable via rq-dashboard
  - Fits existing Python-only stack

Worker startup (add to docker-compose or run manually):
  rq worker emthethal-ingestion emthethal-analytics

Rule: FastAPI enqueues jobs. Workers execute them.
      Workers use the same DB session factory as FastAPI.
      No business logic lives in queue definitions — only task routing.
"""

import logging
import os
from enum import Enum
from typing import Any, Callable, Optional

import redis
from rq import Queue

logger = logging.getLogger(__name__)

# ── Redis Connection ───────────────────────────────────────────────────────────

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

_redis_conn: Optional[redis.Redis] = None


def get_redis() -> redis.Redis:
    """Lazy Redis connection. Returns cached connection."""
    global _redis_conn
    if _redis_conn is None:
        _redis_conn = redis.from_url(REDIS_URL, decode_responses=False)
        logger.info(f"Redis connected: {REDIS_URL}")
    return _redis_conn


# ── Queue Names ───────────────────────────────────────────────────────────────

class QueueName(str, Enum):
    """
    Separate queues for separate pipeline stages.
    Allows independent scaling of OCR workers vs sync workers.
    """
    INGESTION   = "emthethal-ingestion"   # OCR, extraction, canonical generation
    ANALYTICS   = "emthethal-analytics"  # KPI computation, report generation


# ── Queue Registry ────────────────────────────────────────────────────────────

_queues: dict[QueueName, Queue] = {}


def get_queue(name: QueueName) -> Queue:
    """Get or create a named RQ Queue."""
    if name not in _queues:
        _queues[name] = Queue(name.value, connection=get_redis())
    return _queues[name]


# ── Job Enqueue Helpers ───────────────────────────────────────────────────────

def enqueue_ingestion(
    file_bytes: bytes,
    filename: str,
    department: str,
    device_name: str,
    form_type: str,
    document_type: str = "medical_form",
    job_timeout: int = 600,  # 10 min — OCR can be slow on large PDFs
) -> str:
    """
    Enqueue a document ingestion job.
    Returns the job ID for status polling.

    Deferred imports inside the task function prevent circular imports.
    """
    from ..tasks.ingestion_task import run_ingestion_pipeline

    queue = get_queue(QueueName.INGESTION)
    job = queue.enqueue(
        run_ingestion_pipeline,
        kwargs={
            "file_bytes":    file_bytes,
            "filename":      filename,
            "department":    department,
            "device_name":   device_name,
            "form_type":     form_type,
            "document_type": document_type,
        },
        job_timeout=job_timeout,
        result_ttl=3600,   # Keep result for 1 hour
        failure_ttl=86400, # Keep failure info for 24 hours
    )
    logger.info(f"Ingestion job enqueued: job_id={job.id}, file={filename}")
    return job.id


def enqueue_analytics_refresh(job_timeout: int = 120) -> str:
    """
    Enqueue a KPI analytics recomputation job.
    Triggered after each new submission or on schedule.
    """
    from ..tasks.analytics_task import refresh_kpi_analytics

    queue = get_queue(QueueName.ANALYTICS)
    job = queue.enqueue(
        refresh_kpi_analytics,
        job_timeout=job_timeout,
        result_ttl=3600,
    )
    logger.info(f"Analytics refresh job enqueued: job_id={job.id}")
    return job.id


# ── Job Status ────────────────────────────────────────────────────────────────

def get_job_status(job_id: str, queue_name: Optional[QueueName] = None) -> dict[str, Any]:
    """
    Poll the status of a queued job.
    Returns dict with status, result, error.
    """
    from rq.job import Job

    try:
        job = Job.fetch(job_id, connection=get_redis())
        return {
            "job_id":     job_id,
            "status":     job.get_status().value,
            "enqueued_at": job.enqueued_at.isoformat() if job.enqueued_at else None,
            "started_at":  job.started_at.isoformat() if job.started_at else None,
            "ended_at":    job.ended_at.isoformat() if job.ended_at else None,
            "result":     job.result if job.is_finished else None,
            "error":      str(job.exc_info) if job.is_failed else None,
        }
    except Exception as e:
        return {"job_id": job_id, "status": "not_found", "error": str(e)}
