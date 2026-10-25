from sqlalchemy import Column, Integer, String, Text, Boolean, ForeignKey, UniqueConstraint, Enum, Time
from sqlalchemy.orm import relationship
from app.database.base import Base
from app.models.enums import PriorityEnum, TaskStatusEnum, TaskTypeEnum


class TaskMaster(Base):
    __tablename__ = "task_master"

    __table_args__ = (
        UniqueConstraint(
            "department_id",
            "task_name",
            name="uq_department_task"
        ),
    )

    task_id = Column(Integer, primary_key=True)

    task_state = Column(Enum(TaskStatusEnum), nullable=False, default=TaskStatusEnum.ACTIVE)

    department_id = Column(Integer,
    ForeignKey("department.department_id"))

    task_name = Column(String(100), nullable=False)

    description = Column(Text)

    priority_category = Column(Enum(PriorityEnum), nullable=False)

    estimated_time = Column(Integer)

    task_type = Column(Enum(TaskTypeEnum), nullable=False)

    required_role = Column(String(100), nullable=True)

    required_skill = Column(String(255), nullable=True)

    requires_proof = Column(Boolean, nullable=False, default=False, server_default="false")

    suggested_start_time = Column(Time, nullable=True)

    due_time = Column(Time, nullable=True)

    department = relationship(
        "Department",
        back_populates="tasks"
    )

    work_queue_items = relationship(
        "DepartmentWorkQueue",
        back_populates="task"
    )

    schedules = relationship(
        "TaskSchedule",
        back_populates="task",
        cascade="all, delete-orphan",
    )