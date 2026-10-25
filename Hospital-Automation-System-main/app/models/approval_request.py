from sqlalchemy import Column, Integer, String, DateTime, Text, func
from app.database.base import Base


class ApprovalRequest(Base):
    """Stores paused workflow gates that require supervisor approval before resuming.

    Tied to OrchestratorTrace.workflow_id for stateful workflow context persistence.
    """
    __tablename__ = "approval_request"

    approval_id = Column(Integer, primary_key=True)
    workflow_id = Column(String(36), nullable=False, index=True)
    sensitive_action = Column(String(100), nullable=False)
    rationale = Column(Text, nullable=True)
    status = Column(String(30), default="PENDING", nullable=False)
    context_state_json = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    resolved_at = Column(DateTime, nullable=True)
    supervisor_id = Column(Integer, nullable=True)
    supervisor_notes = Column(Text, nullable=True)
