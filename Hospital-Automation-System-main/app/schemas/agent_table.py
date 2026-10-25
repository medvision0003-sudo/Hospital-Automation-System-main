from pydantic import BaseModel, ConfigDict, field_validator
from typing import Optional
from datetime import datetime

from app.utils.standardize import standardize_string


# Create Schema

class AgentTableCreate(BaseModel):
    agent_name: str
    agent_category: str
    description: Optional[str] = None

    @field_validator("agent_name", "agent_category")
    @classmethod
    def standardize_fields(cls, v):
        return standardize_string(v)


# Response Schema

class AgentTableResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    agent_id: int
    agent_name: str
    agent_category: str
    description: Optional[str] = None
    created_at: Optional[datetime] = None
