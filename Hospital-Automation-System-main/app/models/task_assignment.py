
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, func
from sqlalchemy.orm import relationship
from app.database.base import Base
from app.models.enums import AssignmentStatusEnum


class TaskAssignment(Base):
    __tablename__ = "task_assignment"

    assignment_id = Column(Integer, primary_key=True)

    work_id = Column(Integer,
    ForeignKey("department_work_queue.work_id"))

    employee_id = Column(Integer,
    ForeignKey("employee.employee_id"))

    assigned_at = Column(DateTime, server_default=func.now(),nullable=False)

    completed_at = Column(DateTime)

    assignment_status = Column(Enum(AssignmentStatusEnum), default=AssignmentStatusEnum.ASSIGNED,nullable=False)

    # Relationships
    work_queue = relationship(
        "DepartmentWorkQueue",
        back_populates="assignments"
    )

    employee = relationship(
        "Employee",
        back_populates="assignments"
    )
