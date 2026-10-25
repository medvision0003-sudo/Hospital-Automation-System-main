from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, func
from sqlalchemy.orm import relationship
from app.database.base import Base


class WorkflowExperience(Base):
    """Stores past execution failures, recoveries, and supervisor overrides.

    Allows the orchestrator planner to query historical context and learn
    from past decisions at a department or global level.
    """

    __tablename__ = "workflow_experience"

    experience_id = Column(Integer, primary_key=True)

    workflow_id = Column(String(36), nullable=True, index=True)

    department_id = Column(
        Integer, ForeignKey("department.department_id"), nullable=True
    )

    event_type = Column(String(50), nullable=False)

    failed_capability = Column(String(100), nullable=True)

    error_message = Column(Text, nullable=True)

    resolution_type = Column(String(50), nullable=False)

    resolution_action = Column(String(100), nullable=True)

    corrective_steps_json = Column(Text, nullable=True)

    metadata_json = Column(Text, nullable=True)

    experience_summary = Column(Text, nullable=False)

    created_at = Column(
        DateTime, server_default=func.now(), default=datetime.now, nullable=False
    )

    department = relationship("Department")
