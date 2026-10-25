from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime


class OrchestratorTraceListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    workflow_id: str
    event_type: str
    execution_status: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    planning_mode: str = "STATIC"
    planner_status: str = "SUCCESS"


class OrchestratorTraceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    workflow_id: str
    event_type: str
    execution_status: str
    trigger_source: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    input_payload_json: Optional[str] = None
    planned_steps_json: Optional[str] = None
    workflow_execution_json: Optional[str] = None
    produced_outputs_json: Optional[str] = None
    final_result_json: Optional[str] = None
    error_message: Optional[str] = None
    remaining_steps_json: Optional[str] = None
    context_state_json: Optional[str] = None
    planning_mode: str = "STATIC"
    planner_status: str = "SUCCESS"
    sop_referenced: Optional[str] = None
    llm_plan_raw: Optional[str] = None
    validation_errors: Optional[str] = None
