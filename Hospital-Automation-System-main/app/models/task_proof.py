"""
TaskProof Model

Stores proof submissions for completed work queue items.
Each proof tracks the uploaded image path, verification status,
and the rationale from the Task Verification Agent.
"""

from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Enum, func
from sqlalchemy.orm import relationship
from app.database.base import Base
from app.models.enums import TaskProofStatusEnum


class TaskProof(Base):
    __tablename__ = "task_proof"

    proof_id = Column(Integer, primary_key=True)

    work_id = Column(
        Integer,
        ForeignKey("department_work_queue.work_id"),
        nullable=False,
    )

    employee_id = Column(Integer, ForeignKey("employee.employee_id"), nullable=True)

    proof_image_path = Column(String(255), nullable=False)

    verification_status = Column(
        Enum(TaskProofStatusEnum),
        default=TaskProofStatusEnum.PENDING,
        nullable=False,
    )

    verification_confidence = Column(Float, nullable=True)

    verification_rationale = Column(String(1000), nullable=True)

    ai_decision = Column(String(30), nullable=True)

    verification_attempts = Column(Integer, default=1, server_default="1", nullable=False)

    verified_at = Column(DateTime, nullable=True)

    reviewer_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=True)

    submitted_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    work_queue = relationship(
        "DepartmentWorkQueue",
        back_populates="proofs",
    )
