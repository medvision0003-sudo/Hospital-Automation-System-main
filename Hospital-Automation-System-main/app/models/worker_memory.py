
from sqlalchemy import Column, Integer, Float, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from app.database.base import Base


class WorkerMemory(Base):
    __tablename__ = "worker_memory"

    employee_id = Column(
        Integer,
        ForeignKey("employee.employee_id"),
        primary_key=True
    )

    pending_task = Column(Integer)

    total_task_completed = Column(Integer)

    last_updated = Column(DateTime, server_default=func.now(), onupdate=func.now(),nullable=False)

    # Relationships
    employee = relationship(
        "Employee",
        back_populates="worker_memory"
    )