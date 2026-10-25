from sqlalchemy import Column, Integer, Text, ForeignKey, Enum, DateTime, func
from sqlalchemy.orm import relationship
from app.database.base import Base
from app.models.enums import PriorityEnum


class SupervisorTaskRequest(Base):
    __tablename__ = "supervisor_task_request"

    request_id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("task_master.task_id"), nullable=False)
    supervisor_id = Column(Integer, ForeignKey("employee.employee_id"), nullable=False)
    priority = Column(Enum(PriorityEnum), nullable=True)
    due_time = Column(DateTime, nullable=False)
    remarks = Column(Text)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    processed_at = Column(DateTime, nullable=True)

    # Relationships
    task = relationship("TaskMaster")
    supervisor = relationship("Employee")
