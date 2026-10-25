
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, func
from sqlalchemy.orm import relationship
from app.database.base import Base
from app.models.enums import WorkQueueStatusEnum, PriorityEnum


class DepartmentWorkQueue(Base):
    __tablename__ = "department_work_queue"

    work_id = Column(Integer, primary_key=True)

    task_id = Column(
        Integer,
        ForeignKey("task_master.task_id")
    )

    department_id = Column(
        Integer,
        ForeignKey("department.department_id")
    )

    shift_id = Column(Integer, ForeignKey("shift.shift_id"), nullable=True)

    priority = Column(Enum(PriorityEnum), nullable=False)

    queue_status = Column(Enum(WorkQueueStatusEnum), default=WorkQueueStatusEnum.PENDING_ASSIGNED,nullable=False)

    created_at = Column(DateTime, server_default=func.now(),nullable=False)

    due_date = Column(DateTime)

    # Relationships
    task = relationship(
        "TaskMaster",
        back_populates="work_queue_items"
    )

    assignments = relationship(
        "TaskAssignment",
        back_populates="work_queue"
    )

    proofs = relationship(
        "TaskProof",
        back_populates="work_queue",
        cascade="all, delete-orphan",
        order_by="desc(TaskProof.proof_id)",
    )
