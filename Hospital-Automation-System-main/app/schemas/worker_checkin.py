from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import Optional

from app.utils.standardize import standardize_string
from app.models.enums import CheckinStatusEnum


# Create Schema

class WorkerCheckinCreate(BaseModel):
    device_id: str = Field(
        ..., min_length=1, max_length=50,
        description="Device identifier"
    )
    checkin_time: datetime
    employee_id: int = Field(..., gt=0, description="FK to employee")
    checkout_time: Optional[datetime] = None
    status: Optional[CheckinStatusEnum] = CheckinStatusEnum.CHECKED_IN

    @field_validator("device_id")
    @classmethod
    def clean_device_id(cls, v: str) -> str:
        return standardize_string(v)

    @model_validator(mode="after")
    def check_times(self):
        if self.checkout_time and self.checkout_time < self.checkin_time:
            raise ValueError("checkout_time cannot be before checkin_time")
        return self


# Update Schema (partial)

class WorkerCheckinUpdate(BaseModel):
    employee_id: Optional[int] = Field(None, gt=0)
    checkout_time: Optional[datetime] = None
    status: Optional[CheckinStatusEnum] = None


# Response Schema

class WorkerCheckinResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    device_id: str
    checkin_time: datetime
    employee_id: Optional[int] = None
    checkout_time: Optional[datetime] = None
    status: Optional[str] = None
