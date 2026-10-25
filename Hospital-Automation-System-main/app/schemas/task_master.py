from pydantic import BaseModel, ConfigDict, field_validator
from typing import Optional
from datetime import datetime, time

from app.utils.standardize import standardize_string, standardize_skills
from app.models.enums import PriorityEnum, TaskStatusEnum, TaskTypeEnum
from app.schemas.task_schedule import TaskScheduleResponse


class TaskCreate(BaseModel):
    department_id: Optional[int] = None
    task_name: str
    description: Optional[str] = None
    priority_category: Optional[PriorityEnum] = PriorityEnum.MEDIUM
    estimated_time: Optional[int] = None
    task_state: Optional[TaskStatusEnum] = TaskStatusEnum.ACTIVE
    task_type: TaskTypeEnum
    required_role: Optional[str] = None
    required_skill: Optional[str] = None
    requires_proof: bool = False
    suggested_start_time: Optional[time] = None
    due_time: Optional[time] = None

    @field_validator("task_name")
    @classmethod
    def standardize_fields(cls, v):
        return standardize_string(v)

    @field_validator("required_skill")
    @classmethod
    def clean_required_skill(cls, v):
        return standardize_skills(v)

    @field_validator("required_role")
    @classmethod
    def clean_required_role(cls, v):
        return standardize_string(v)


class TaskUpdate(BaseModel):
    department_id: Optional[int] = None
    task_name: Optional[str] = None
    description: Optional[str] = None
    priority_category: Optional[PriorityEnum] = None
    estimated_time: Optional[int] = None
    task_state: Optional[TaskStatusEnum] = None
    task_type: Optional[TaskTypeEnum] = None
    required_role: Optional[str] = None
    required_skill: Optional[str] = None
    requires_proof: Optional[bool] = None
    suggested_start_time: Optional[time] = None
    due_time: Optional[time] = None

    @field_validator("task_name")
    @classmethod
    def standardize_fields(cls, v):
        return standardize_string(v)

    @field_validator("required_skill")
    @classmethod
    def clean_required_skill(cls, v):
        return standardize_skills(v)

    @field_validator("required_role")
    @classmethod
    def clean_required_role(cls, v):
        return standardize_string(v)


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_id: int
    department_id: Optional[int] = None
    task_name: str
    description: Optional[str] = None
    priority_category: Optional[str] = None
    estimated_time: Optional[int] = None
    task_state: Optional[TaskStatusEnum] = None
    task_type: TaskTypeEnum
    required_role: Optional[str] = None
    required_skill: Optional[str] = None
    requires_proof: bool = False
    suggested_start_time: Optional[time] = None
    due_time: Optional[time] = None
    schedules: list[TaskScheduleResponse] = []
