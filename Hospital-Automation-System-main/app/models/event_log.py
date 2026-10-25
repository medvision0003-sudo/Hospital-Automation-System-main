
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, func
from sqlalchemy.orm import relationship
from app.database.base import Base


class EventLog(Base):
    __tablename__ = "event_log"

    event_id = Column(Integer, primary_key=True)

    event_log = Column(String(255), nullable=False)

    source_module = Column(String(50), nullable=False)

    employee_id = Column(
        Integer,
        ForeignKey("employee.employee_id")
    )

    work_id = Column(
        Integer,
        ForeignKey("department_work_queue.work_id")
    )

    assignment_id = Column(
        Integer,
        ForeignKey("task_assignment.assignment_id")
    )

    timestamp = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    agent_actions = relationship(
        "AgentActionLog",
        back_populates="event"
    )
