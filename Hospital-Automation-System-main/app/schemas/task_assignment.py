from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Optional

from app.models.enums import AssignmentStatusEnum


# Create Schema

class TaskAssignmentCreate(BaseModel):
    work_id: int = Field(..., gt=0, description="FK to department_work_queue")
    employee_id: int = Field(..., gt=0, description="FK to employee")
    assigned_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    assignment_status: Optional[AssignmentStatusEnum] = AssignmentStatusEnum.ASSIGNED

    @model_validator(mode="after")
    def check_dates(self):
        if self.completed_at and self.assigned_at:
            if self.completed_at < self.assigned_at:
                raise ValueError("completed_at cannot be before assigned_at")
        return self


# Update Schema (partial)

class TaskAssignmentUpdate(BaseModel):
    work_id: Optional[int] = Field(None, gt=0)
    employee_id: Optional[int] = Field(None, gt=0)
    assigned_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    assignment_status: Optional[AssignmentStatusEnum] = None

    @model_validator(mode="after")
    def check_dates(self):
        if self.completed_at and self.assigned_at:
            if self.completed_at < self.assigned_at:
                raise ValueError("completed_at cannot be before assigned_at")
        return self


# Response Schema

class TaskAssignmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    assignment_id: int
    work_id: Optional[int] = None
    employee_id: Optional[int] = None
    assigned_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    assignment_status: Optional[str] = None


class AutoAssignResponse(BaseModel):
    """Returned by the auto-assign endpoint after a successful assignment."""
    assignment_id: int
    event_id: int
    agent_action_id: int
    employee_id: int
    employee_name: str

