from sqlalchemy import (
    Column, Integer, String, DateTime, Boolean,
    ForeignKey, UniqueConstraint, Enum,
)
from sqlalchemy.orm import relationship

from app.database.base import Base
from app.models.enums import FrequencyTypeEnum


class TaskSchedule(Base):
    __tablename__ = "task_schedule"

    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "schedule_name",
            name="uq_task_schedule_name",
        ),
    )

    schedule_id = Column(Integer, primary_key=True)

    task_id = Column(
        Integer,
        ForeignKey("task_master.task_id", ondelete="CASCADE"),
        nullable=False,
    )

    shift_id = Column(
        Integer,
        ForeignKey("shift.shift_id"),
        nullable=True,
    )

    schedule_name = Column(String(100), nullable=False)

    frequency_type = Column(Enum(FrequencyTypeEnum), nullable=False)

    frequency_value = Column(Integer, nullable=False, default=1)

    next_run = Column(DateTime, nullable=False, index=True)

    last_run = Column(DateTime, nullable=True)

    is_active = Column(Boolean, nullable=False, default=True)

    task = relationship(
        "TaskMaster",
        back_populates="schedules",
    )

    shift = relationship(
        "Shift",
        backref="task_schedules",
    )

    @property
    def shift_name(self):
        return self.shift.shift_name if self.shift else None
