from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Enum, DateTime, text, Text, Float
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy import event

import enum
from datetime import datetime

Base = declarative_base()




class IngestedDocument(Base):
    """Tracks every document that passes through the ingestion pipeline."""
    __tablename__ = "ingested_documents"

    id = Column(Integer, primary_key=True, index=True)
    source_filename = Column(String, nullable=False, index=True)
    file_type = Column(String, nullable=False)  # pdf, docx, xlsx
    document_type = Column(String, nullable=False, default="medical_form")
    department = Column(String, nullable=False, default="General")
    device_name = Column(String, nullable=False, default="General")
    form_type = Column(String, nullable=False, default="General")
    status = Column(String, nullable=False, default="pass")  # pass, warning, hard_stop
    quarantine_flag = Column(Boolean, default=False)
    avg_confidence = Column(String, nullable=True)  # stored as string for precision
    total_blocks = Column(Integer, default=0)
    total_rows = Column(Integer, default=0)
    chunks_stored = Column(Integer, default=0)
    violations = Column(JSONB, nullable=True)  # list of quarantine violations
    processing_metadata = Column(JSONB, nullable=True)
    created_at = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

class TemplateStatus(enum.Enum):
    Draft = "Draft"
    Pending_QA_Review = "Pending_QA_Review"
    Approved = "Approved"
    Archived = "Archived"


class FormLifecycleState(enum.Enum):
    """Gap #2: Formal QA state machine states. Mirrors core/qa_state_machine.py."""
    INGESTED    = "INGESTED"
    EXTRACTED   = "EXTRACTED"
    GENERATED   = "GENERATED"
    QUARANTINED = "QUARANTINED"
    QA_PENDING  = "QA_PENDING"
    REJECTED    = "REJECTED"
    APPROVED    = "APPROVED"
    LIVE        = "LIVE"
    SUPERSEDED  = "SUPERSEDED"
    CLOSED      = "CLOSED"

class DeviceStatus(enum.Enum):
    Active = "Active"
    Frozen = "Frozen"

class Department(Base):
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    ahsan_ref_code = Column(String, unique=True, index=True)

    devices = relationship("Device", back_populates="department")
    templates = relationship("ChecklistTemplate", back_populates="department")

class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, index=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    name = Column(String, nullable=False)
    serial_number = Column(String, unique=True, index=True)
    is_life_support = Column(Boolean, default=False)
    status = Column(Enum(DeviceStatus), default=DeviceStatus.Active)

    department = relationship("Department", back_populates="devices")
    logs = relationship("InspectionLog", back_populates="device")

class ChecklistTemplate(Base):
    __tablename__ = "checklist_templates"

    id             = Column(Integer, primary_key=True, index=True)
    title          = Column(String, nullable=False)
    department_id  = Column(Integer, ForeignKey("departments.id"), nullable=False)

    # ── Canonical Schema (Gap #1 + #2) ────────────────────────────────────────
    canonical_schema   = Column(JSONB, nullable=True)   # CanonicalFormSchema v2 JSON
    schema_version     = Column(String, nullable=True, default="2.0.0")  # semver
    schema_hash        = Column(String, nullable=True, index=True)       # SHA-256
    source_document_id = Column(Integer, ForeignKey("ingested_documents.id"), nullable=True)

    # ── Rendered outputs (derived from canonical) ──────────────────────────────
    form_schema = Column(JSONB, nullable=False)   # Form.io JSON (QA preview)
    criteria    = Column(JSONB, nullable=False)   # [{key, label, is_fatal}]

    # ── QA State Machine (Gap #2) ─────────────────────────────────────────────
    lifecycle_state = Column(
        Enum(FormLifecycleState),
        default=FormLifecycleState.GENERATED,
        nullable=False,
        index=True,
    )
    # Legacy status kept for backward compat with existing routes
    status = Column(Enum(TemplateStatus), default=TemplateStatus.Pending_QA_Review)

    # ── Confidence Governance (Gap #4) ────────────────────────────────────────
    avg_confidence       = Column(Float, nullable=True)
    confidence_outcome   = Column(String, nullable=True)  # AUTO_PASS | QA_REVIEW | QUARANTINE


    created_at = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    # ── Optimistic Locking ───────────────────────────────────────────────────
    # Prevents concurrent QA edits from silently overwriting each other.
    # SQLAlchemy raises StaleDataError if version_id doesn't match on UPDATE.
    version_id = Column(Integer, nullable=False, server_default="1")

    __mapper_args__ = {"version_id_col": version_id}

    department = relationship("Department", back_populates="templates")
    logs       = relationship("InspectionLog", back_populates="template")
    qa_transitions = relationship("QAStateAuditLog", back_populates="template", cascade="all, delete-orphan")

class InspectionLog(Base):
    __tablename__ = "inspection_logs"

    id             = Column(Integer, primary_key=True, index=True)
    device_id      = Column(Integer, ForeignKey("devices.id"), nullable=False)
    template_id    = Column(Integer, ForeignKey("checklist_templates.id"), nullable=False)
    inspector_name = Column(String, nullable=False)
    inspection_data = Column(JSONB, nullable=False)  # Submitted form data (live answers)
    has_fatal_failure = Column(Boolean, default=False)
    created_at     = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    # ── Gap #3: Immutable Submission Snapshots ────────────────────────────────
    # Store the EXACT schema at the time of submission.
    # These columns are WRITE-ONCE. Never updated after creation.
    # Without this: historical analytics and KPI comparisons break when forms evolve.
    submitted_schema_snapshot = Column(JSONB, nullable=True)  # CanonicalFormSchema at submit time
    submitted_formio_snapshot = Column(JSONB, nullable=True)  # Form.io JSON at submit time
    schema_version            = Column(String, nullable=True)  # e.g. "2.0.0"
    schema_hash               = Column(String, nullable=True)  # SHA-256 of canonical at submit time

    # ── Submission Source ─────────────────────────────────────────────────────
    submission_source    = Column(String, default="react")   # "react"

    device   = relationship("Device", back_populates="logs")
    template = relationship("ChecklistTemplate", back_populates="logs")


class QAStateAuditLog(Base):
    """
    Gap #2: Immutable audit log of every QA state transition.
    One row per transition. Never updated or deleted.
    Enables: full audit trail, actor accountability, debugging.
    """
    __tablename__ = "qa_state_audit_log"

    id          = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("checklist_templates.id"), nullable=False)
    from_state  = Column(String, nullable=False)   # FormLifecycleState value
    to_state    = Column(String, nullable=False)   # FormLifecycleState value
    actor       = Column(String, nullable=False)   # "system" | "user:<id>"
    notes       = Column(Text, nullable=True)
    transitioned_at = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    template = relationship("ChecklistTemplate", back_populates="qa_transitions")


class FailedJobRecord(Base):
    """
    Dead-letter queue: every failed RQ job is recorded here.

    Enables:
    - Operator visibility into failures without digging through Redis logs
    - Retry tracking with exponential backoff policy
    - Alert thresholds (e.g. alert if retry_count > 3)
    - Audit of what failed and why

    Retry policy (exponential backoff):
      retry_at = last_failed_at + (2 ** retry_count) * 60 seconds
      Max retries: 5 (after that, status = 'dead')
    """
    __tablename__ = "failed_job_records"

    id            = Column(Integer, primary_key=True, index=True)
    job_id        = Column(String, nullable=False, unique=True, index=True)   # RQ job UUID
    queue_name    = Column(String, nullable=False)   # emthethal-ingestion | ...
    task_function = Column(String, nullable=False)   # e.g. "app.tasks.ingestion_task.run_ingestion_pipeline"
    task_kwargs   = Column(JSONB, nullable=True)     # Redacted copy of job kwargs (no raw bytes)
    error_type    = Column(String, nullable=True)    # Exception class name
    error_message = Column(Text, nullable=True)      # Exception message
    traceback     = Column(Text, nullable=True)      # Full traceback
    retry_count   = Column(Integer, default=0, nullable=False)
    max_retries   = Column(Integer, default=5, nullable=False)
    status        = Column(String, default="failed", nullable=False, index=True)
    # status values: "failed" | "retrying" | "dead" | "resolved"
    first_failed_at = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    last_failed_at  = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"), onupdate=text("CURRENT_TIMESTAMP"))
    retry_at        = Column(DateTime, nullable=True)   # When to next attempt retry
    resolved_at     = Column(DateTime, nullable=True)


class OriginalFileRecord(Base):
    """
    Object storage tracking: every uploaded file is stored in MinIO/S3.

    Rule: FastAPI never operates on temp files in /tmp.
    Every file uploaded via /ingest gets a permanent object key in MinIO.
    This record links the object key to the ingested document for reprocessing.

    Enables:
    - Re-ingestion without re-upload
    - Audit of original source files
    - Legal/compliance hold capability
    """
    __tablename__ = "original_file_records"

    id             = Column(Integer, primary_key=True, index=True)
    document_id    = Column(Integer, ForeignKey("ingested_documents.id"), nullable=False, unique=True)
    bucket_name    = Column(String, nullable=False, default="emthethal-originals")
    object_key     = Column(String, nullable=False, unique=True, index=True)
    # e.g. "uploads/2026/05/13/{uuid4}_{filename}"
    original_filename = Column(String, nullable=False)
    file_size_bytes   = Column(Integer, nullable=True)
    content_type      = Column(String, nullable=True)
    checksum_sha256   = Column(String, nullable=True)   # File integrity verification
    storage_backend   = Column(String, default="minio")  # "minio" | "s3" | "local"
    uploaded_at       = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
