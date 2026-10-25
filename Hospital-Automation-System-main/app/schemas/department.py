from pydantic import BaseModel, ConfigDict, field_validator
from typing import Optional

from app.utils.standardize import standardize_string


class DepartmentBase(BaseModel):
    department_name: str
    description: Optional[str] = None

    @field_validator("department_name")
    @classmethod
    def standardize_name(cls, v):
        return standardize_string(v)


class DepartmentCreate(DepartmentBase):
    pass



class DepartmentUpdate(BaseModel):
    department_name: Optional[str] = None
    description: Optional[str] = None

    @field_validator("department_name")
    @classmethod
    def standardize_name(cls, v):
        return standardize_string(v)


class DepartmentResponse(BaseModel):
    department_id: int
    department_name: str
    description: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
