from pydantic import BaseModel, ConfigDict, field_validator
from typing import Optional
from datetime import datetime

from app.utils.standardize import standardize_string
from app.models.enums import AgentActionStatusEnum


# Create Schema

class AgentActionCreate(BaseModel):
    event_id: Optional[int] = None
    department_id: Optional[int] = None
    agent_id: Optional[int] = None
    action_type: Optional[str] = None
    action_timestamp: Optional[datetime] = None
    execution_status: Optional[AgentActionStatusEnum] = AgentActionStatusEnum.PENDING
    decision_summary: Optional[str] = None
    reasoning_engine: Optional[str] = None
    execution_time_ms: Optional[int] = None

    @field_validator("action_type", "reasoning_engine")
    @classmethod
    def standardize_fields(cls, v):
        return standardize_string(v)


# Response Schema

class AgentActionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    agent_action_id: int
    event_id: Optional[int] = None
    department_id: Optional[int] = None
    agent_id: Optional[int] = None
    action_type: Optional[str] = None
    action_timestamp: Optional[datetime] = None
    execution_status: Optional[str] = None
    decision_summary: Optional[str] = None
    reasoning_engine: Optional[str] = None
    execution_time_ms: Optional[int] = None
    agent_name: Optional[str] = None
    workflow_id: Optional[str] = None
