from pydantic import BaseModel, ConfigDict, field_validator
from typing import Optional
from datetime import datetime

from app.utils.standardize import standardize_string


# Create Schema

class EventLogCreate(BaseModel):
    event_log: Optional[str] = None
    source_module: Optional[str] = None
    employee_id: Optional[int] = None
    work_id: Optional[int] = None
    assignment_id: Optional[int] = None
    timestamp: Optional[datetime] = None

    @field_validator("source_module")
    @classmethod
    def standardize_fields(cls, v):
        return standardize_string(v)


# Response Schema

class EventLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: int
    event_log: Optional[str] = None
    source_module: Optional[str] = None
    employee_id: Optional[int] = None
    work_id: Optional[int] = None
    assignment_id: Optional[int] = None
    timestamp: Optional[datetime] = None
