from datetime import date, datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NursingShiftLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    log_id: int
    submitted_at: datetime
    nurse_name: str
    shift_date: date
    shift_name: str
    ward_area: str
    answers: Dict[str, Any]


class NursingShiftLogCreate(BaseModel):
    submitted_at: Optional[datetime] = None
    nurse_name: str = Field(..., min_length=1, max_length=255)
    shift_date: date
    shift_name: str = Field(..., min_length=1, max_length=100)
    ward_area: str = Field(..., min_length=1, max_length=255)
    answers: Dict[str, Any]

    @field_validator("nurse_name", "shift_name", "ward_area")
    @classmethod
    def require_non_whitespace(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Value must not be blank.")
        return value
