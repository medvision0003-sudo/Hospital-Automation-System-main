from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional

from app.utils.standardize import standardize_string, standardize_skills
from app.models.enums import EmploymentStatusEnum, GenderEnum


# Create Schema

class EmployeeCreate(BaseModel):
    department_id: Optional[int] = Field(None, gt=0, description="FK to department")
    name: str = Field(..., min_length=2, max_length=100, description="Full name")
    role: str = Field(..., min_length=2, max_length=100, description="Job role")
    phone: Optional[int] = Field(None, ge=1_000_000_000, le=9_999_999_999, description="Phone number (digits only)")
    availability: Optional[EmploymentStatusEnum] = EmploymentStatusEnum.ACTIVE
    gender: GenderEnum
    skill: Optional[str] = Field(None, max_length=255, description="Comma-separated list of specialized skills")
    experience_years: Optional[int] = Field(0, ge=0, description="Years of professional experience")

    @field_validator("name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        return standardize_string(v)

    @field_validator("skill")
    @classmethod
    def clean_skill(cls, v: Optional[str]) -> Optional[str]:
        return standardize_skills(v)


# Update Schema (partial)

class EmployeeUpdate(BaseModel):
    department_id: Optional[int] = Field(None, gt=0)
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    role: Optional[str] = Field(None, min_length=2, max_length=100)
    phone: Optional[int] = Field(None, ge=1_000_000_000, le=9_999_999_999)
    availability: Optional[EmploymentStatusEnum] = None
    gender: Optional[GenderEnum] = None
    skill: Optional[str] = Field(None, max_length=255)
    experience_years: Optional[int] = Field(None, ge=0)

    @field_validator("name")
    @classmethod
    def clean_name(cls, v: Optional[str]) -> Optional[str]:
        return standardize_string(v)

    @field_validator("skill")
    @classmethod
    def clean_skill(cls, v: Optional[str]) -> Optional[str]:
        return standardize_skills(v)


# Response Schema

class EmployeeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    employee_id: int
    department_id: Optional[int] = None
    name: str
    role: Optional[str] = None
    phone: Optional[int] = None
    availability: Optional[str] = None
    gender: Optional[str] = None
    skill: Optional[str] = None
    experience_years: int = 0
    pending_task: Optional[int] = None
    high_critical_count: Optional[int] = None
    total_task_completed: Optional[int] = None
    department_name: Optional[str] = None
