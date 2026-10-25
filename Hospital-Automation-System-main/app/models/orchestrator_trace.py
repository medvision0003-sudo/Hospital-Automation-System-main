from sqlalchemy import Column, String, DateTime, Text, func
from app.database.base import Base


class OrchestratorTrace(Base):
    __tablename__ = "orchestrator_trace"

    workflow_id = Column(String(36), primary_key=True, index=True)
    event_type = Column(String(50), nullable=False)
    execution_status = Column(String(50), default="PENDING", nullable=False)
    trigger_source = Column(String(50), nullable=True)
    started_at = Column(DateTime, server_default=func.now(), nullable=False)
    completed_at = Column(DateTime, nullable=True)

    # JSON payloads stored as Text for SQLite compatibility
    input_payload_json = Column(Text, nullable=True)
    planned_steps_json = Column(Text, nullable=True)
    workflow_execution_json = Column(Text, nullable=True)
    produced_outputs_json = Column(Text, nullable=True)
    final_result_json = Column(Text, nullable=True)

    error_message = Column(Text, nullable=True)

    # Paused workflow state for resume support
    remaining_steps_json = Column(Text, nullable=True)
    context_state_json = Column(Text, nullable=True)

    # SOP-grounded planner audit fields
    planning_mode = Column(String(30), default="STATIC", nullable=False)
    planner_status = Column(String(30), default="SUCCESS", nullable=False)
    sop_referenced = Column(String(100), nullable=True)
    llm_plan_raw = Column(Text, nullable=True)
    validation_errors = Column(Text, nullable=True)
