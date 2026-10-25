from datetime import time
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import Optional

from app.utils.standardize import standardize_string


# Create Schema

class ShiftCreate(BaseModel):
    department_id: Optional[int] = Field(None, description="Optional FK to department; None for global template")
    shift_name: str = Field(..., min_length=1, max_length=100, description="Name of the shift")
    start_time: time
    end_time: time

    @field_validator("shift_name")
    @classmethod
    def clean_shift_name(cls, v: str) -> str:
        return standardize_string(v)

    @model_validator(mode="after")
    def reject_equal_times(self):
        if self.start_time == self.end_time:
            raise ValueError(
                "start_time and end_time cannot be equal; "
                "24-hour recurring shift windows are not supported"
            )
        return self


# Update Schema (partial)

class ShiftUpdate(BaseModel):
    department_id: Optional[int] = Field(None, gt=0)
    shift_name: Optional[str] = Field(None, min_length=1, max_length=100)
    start_time: Optional[time] = None
    end_time: Optional[time] = None

    @field_validator("shift_name")
    @classmethod
    def clean_shift_name(cls, v: Optional[str]) -> Optional[str]:
        return standardize_string(v)

    @model_validator(mode="after")
    def reject_equal_times_when_both_present(self):
        if self.start_time is not None and self.end_time is not None:
            if self.start_time == self.end_time:
                raise ValueError(
                    "start_time and end_time cannot be equal; "
                    "24-hour recurring shift windows are not supported"
                )
        return self


# Response Schema

class ShiftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    shift_id: int
    department_id: Optional[int] = None
    shift_name: str
    start_time: time
    end_time: time

