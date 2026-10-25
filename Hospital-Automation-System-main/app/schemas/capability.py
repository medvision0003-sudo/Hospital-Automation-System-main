from pydantic import BaseModel
from typing import Optional


class CapabilityResponse(BaseModel):
    name: str
    agent_name: str
    handles_events: list[str]
    requires: list[str]
    produces: list[str]
    priority: int
    continue_on_failure: bool = False
    description: str = ""


class AgentStatsResponse(BaseModel):
    agent_id: int
    agent_name: str
    total_executions: int
    success_count: int
    failed_count: int
    pending_count: int
    success_rate: float
    avg_execution_time_ms: Optional[float] = None
    last_active: Optional[str] = None
