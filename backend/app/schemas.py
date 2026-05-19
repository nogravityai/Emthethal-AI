from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime
from enum import Enum

# Enums matching models.py
class TemplateStatus(str, Enum):
    Draft = "Draft"
    Pending_QA_Review = "Pending_QA_Review"
    Approved = "Approved"
    Archived = "Archived"

class DeviceStatus(str, Enum):
    Active = "Active"
    Frozen = "Frozen"

# Criteria Schema for AI Extraction
class ChecklistCriterion(BaseModel):
    key: str = Field(..., description="The unique key of the form component")
    label: str = Field(..., description="Human readable label for the check")
    is_fatal: bool = Field(default=False, description="If true, failing this freezes the device")

# Form.io Component Schema (simplified for validation)
class FormioComponent(BaseModel):
    type: str
    key: str
    label: str
    values: Optional[List[Dict[str, str]]] = None
    validate: Optional[Dict[str, Any]] = None

# AI Generated Template Schema
class AIGeneratedTemplate(BaseModel):
    title: str
    form_schema: Dict[str, Any] = Field(..., description="Form.io JSON schema")
    criteria: List[ChecklistCriterion] = Field(..., description="List of fatal/non-fatal checks")

# Inspection Submission
class InspectionSubmit(BaseModel):
    device_id: int
    template_id: int
    inspector_name: str
    inspection_data: Dict[str, Any] = Field(..., description="Form.io submission payload (keys match criteria keys)")

# API Schemas
class DepartmentBase(BaseModel):
    name: str
    ahsan_ref_code: str

class DepartmentCreate(DepartmentBase):
    pass

class Department(DepartmentBase):
    id: int
    class Config:
        from_attributes = True

class DeviceBase(BaseModel):
    name: str
    serial_number: str
    department_id: int
    is_life_support: bool = False

class Device(DeviceBase):
    id: int
    status: DeviceStatus
    class Config:
        from_attributes = True

class ChecklistTemplateBase(BaseModel):
    title: str
    department_id: int
    form_schema: Dict[str, Any]
    criteria: List[ChecklistCriterion]

class ChecklistTemplate(ChecklistTemplateBase):
    id: int
    status: TemplateStatus
    created_at: datetime
    class Config:
        from_attributes = True

class KPIStats(BaseModel):
    frozen_ratio: float
    total_devices: int
    frozen_devices: int
    icu_occupancy_impact: int
