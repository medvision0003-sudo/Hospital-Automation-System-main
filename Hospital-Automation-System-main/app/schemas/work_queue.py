from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime

from app.models.enums import PriorityEnum, WorkQueueStatusEnum


# Create Schema

class WorkQueueCreate(BaseModel):
    task_id: Optional[int] = None
    department_id: Optional[int] = None
    shift_id: Optional[int] = None
    priority: Optional[PriorityEnum] = PriorityEnum.MEDIUM
    queue_status: Optional[WorkQueueStatusEnum] = WorkQueueStatusEnum.PENDING_ASSIGNED
    created_at: Optional[datetime] = None
    due_date: Optional[datetime] = None


# Update Schema (partial)

class WorkQueueUpdate(BaseModel):
    task_id: Optional[int] = None
    department_id: Optional[int] = None
    shift_id: Optional[int] = None
    priority: Optional[PriorityEnum] = None
    queue_status: Optional[WorkQueueStatusEnum] = None
    due_date: Optional[datetime] = None


# Response Schema

class WorkQueueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    work_id: int
    task_id: Optional[int] = None
    department_id: Optional[int] = None
    shift_id: Optional[int] = None
    priority: Optional[str] = None
    queue_status: Optional[str] = None
    created_at: Optional[datetime] = None
    due_date: Optional[datetime] = None
    proof_image_path: Optional[str] = None
    verification_status: Optional[str] = None
    verification_confidence: Optional[float] = None
    verification_rationale: Optional[str] = None
    ai_decision: Optional[str] = None
    proof_employee_id: Optional[int] = None
    verification_attempts: Optional[int] = None
