# app/models/__init__.py
# Re-exports ALL SQLAlchemy ORM models from orm.py so that existing imports
# like `from app.models import ChecklistTemplate` continue to work unchanged.
# CFIS Pydantic schemas live in app/models/schemas.py (separate namespace).

from app.models.orm import (
    Base,
    IngestedDocument,
    TemplateStatus,
    FormLifecycleState,
    DeviceStatus,
    Department,
    Device,
    ChecklistTemplate,
    InspectionLog,
    QAStateAuditLog,
    FailedJobRecord,
    OriginalFileRecord,
)

__all__ = [
    "Base",
    "IngestedDocument",
    "TemplateStatus",
    "FormLifecycleState",
    "DeviceStatus",
    "Department",
    "Device",
    "ChecklistTemplate",
    "InspectionLog",
    "QAStateAuditLog",
    "FailedJobRecord",
    "OriginalFileRecord",
]
