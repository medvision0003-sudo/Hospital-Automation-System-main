from pydantic import BaseModel, ConfigDict, field_validator
from typing import Optional
from datetime import datetime

from app.utils.standardize import standardize_string
from app.models.enums import FrequencyTypeEnum


class TaskScheduleCreate(BaseModel):
    task_id: int
    shift_id: Optional[int] = None
    schedule_name: str
    frequency_type: FrequencyTypeEnum
    frequency_value: int = 1
    next_run: Optional[datetime] = None

    @field_validator("schedule_name")
    @classmethod
    def standardize_fields(cls, v):
        return standardize_string(v)


class TaskScheduleUpdate(BaseModel):
    shift_id: Optional[int] = None
    schedule_name: Optional[str] = None
    frequency_type: Optional[FrequencyTypeEnum] = None
    frequency_value: Optional[int] = None
    next_run: Optional[datetime] = None
    is_active: Optional[bool] = None

    @field_validator("schedule_name")
    @classmethod
    def standardize_fields(cls, v):
        return standardize_string(v)


class TaskScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    schedule_id: int
    task_id: int
    shift_id: Optional[int] = None
    shift_name: Optional[str] = None
    schedule_name: str
    frequency_type: FrequencyTypeEnum
    frequency_value: int
    next_run: Optional[datetime] = None
    last_run: Optional[datetime] = None
    is_active: bool
