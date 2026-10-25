from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime
from typing import Optional


# Update Schema

class WorkerMemoryUpdate(BaseModel):
    pending_task: Optional[int] = Field(None, ge=0)
    total_task_completed: Optional[int] = Field(None, ge=0)


# Response Schema

class WorkerMemoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    employee_id: int
    pending_task: Optional[int] = None
    total_task_completed: Optional[int] = None
    last_updated: Optional[datetime] = None

