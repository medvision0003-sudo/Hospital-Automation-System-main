# These schemas represent the shift scheduling data models. The backend names these as ShiftRoster,
# while the database table is mapped to "shift_scheduler" and the frontend uses the term "scheduler" / "ShiftScheduler".
from datetime import date
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional

from app.models.enums import RosterStatusEnum


# Create Schema

class ShiftRosterCreate(BaseModel):
    employee_id: int = Field(..., gt=0, description="FK to employee")
    shift_id: int = Field(..., gt=0, description="FK to shift")
    work_date: date
    roster_status: Optional[RosterStatusEnum] = RosterStatusEnum.SCHEDULED


# Update Schema (partial)

class ShiftRosterUpdate(BaseModel):
    employee_id: Optional[int] = Field(None, gt=0)
    shift_id: Optional[int] = Field(None, gt=0)
    work_date: Optional[date] = None
    roster_status: Optional[RosterStatusEnum] = None


# Response Schema

class ShiftRosterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    roster_id: int
    employee_id: int
    shift_id: int
    work_date: date
    roster_status: Optional[str] = None
