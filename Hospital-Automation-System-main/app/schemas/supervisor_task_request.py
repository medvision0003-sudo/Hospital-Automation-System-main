from pydantic import BaseModel, ConfigDict, Field
from typing import Optional
from datetime import datetime
from app.models.enums import PriorityEnum, DueOffsetEnum


class SupervisorTaskRequestCreate(BaseModel):
    task_id: int = Field(..., gt=0)
    supervisor_id: int = Field(..., gt=0)
    priority: Optional[PriorityEnum] = None
    due_time: Optional[datetime] = None
    due_offset: Optional[DueOffsetEnum] = None
    remarks: Optional[str] = None


class SupervisorTaskRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    request_id: int
    task_id: int
    supervisor_id: int
    priority: Optional[PriorityEnum] = None
    due_time: datetime
    remarks: Optional[str] = None
    created_at: datetime
    processed_at: Optional[datetime] = None


class SupervisorTaskRequestsBulkResponse(BaseModel):
    created: int
    requests: list[SupervisorTaskRequestResponse]
