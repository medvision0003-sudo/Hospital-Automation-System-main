
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Enum, Boolean, func
from sqlalchemy.orm import relationship
from app.database.base import Base
from app.models.enums import AgentActionStatusEnum


class AgentActionLog(Base):
    __tablename__ = "agent_action_log"

    agent_action_id = Column(Integer, primary_key=True)

    event_id = Column(
        Integer,
        ForeignKey("event_log.event_id")
    )

    department_id = Column(
        Integer,
        ForeignKey("department.department_id")
    )

    agent_id = Column(
        Integer,
        ForeignKey("agent_table.agent_id")
    )

    action_type = Column(String(50),nullable=False)

    action_timestamp = Column(DateTime, server_default=func.now(),nullable=False)

    execution_status = Column(Enum(AgentActionStatusEnum), default=AgentActionStatusEnum.PENDING, nullable=False)

    decision_summary = Column(Text)

    reasoning_engine = Column(String(50))

    execution_time_ms = Column(Integer)

    # Supervisor resolution tracking columns
    is_resolved = Column(Boolean, default=False, nullable=False)
    resolved_at = Column(DateTime, nullable=True)
    supervisor_id = Column(Integer, nullable=True)
    supervisor_notes = Column(Text, nullable=True)
    resolution_action = Column(Text, nullable=True)

    # Orchestrator workflow link for pause/resume support
    workflow_id = Column(String(36), nullable=True, index=True)

    # Relationships
    event = relationship(
        "EventLog",
        back_populates="agent_actions"
    )

    agent = relationship(
        "AgentTable",
        back_populates="actions"
    )

    @property
    def agent_name(self):
        return self.agent.agent_name if self.agent else None
