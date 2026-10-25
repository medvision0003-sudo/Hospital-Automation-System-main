from sqlalchemy import Column, Integer, Date, DateTime, Boolean, ForeignKey, Enum
from sqlalchemy.orm import relationship

from app.database.base import Base
from app.models.enums import RosterStatusEnum


# This model represents the shift scheduling system. While the backend uses the class name ShiftRoster,
# related schemas, and endpoints (/rosters), the database table is mapped to "shift_scheduler"
# and the frontend uses the term "scheduler" / "ShiftScheduler".
class ShiftRoster(Base):
    __tablename__ = "shift_scheduler"

    roster_id = Column(Integer, primary_key=True, autoincrement=True)

    employee_id = Column(
        Integer,
        ForeignKey("employee.employee_id"),
        nullable=False,
    )

    shift_id = Column(
        Integer,
        ForeignKey("shift.shift_id"),
        nullable=False,
    )

    work_date = Column(Date, nullable=False)

    roster_status = Column(
        Enum(RosterStatusEnum),
        default=RosterStatusEnum.SCHEDULED,
        nullable=False,
    )

    # Overtime tracking columns
    is_overtime = Column(Boolean, default=False, server_default="0", nullable=False)
    overtime_duration_hours = Column(Integer, nullable=True)
    overtime_end_time = Column(DateTime, nullable=True)

    # Relationships
    employee = relationship(
        "Employee",
        back_populates="roster_entries",
    )

    shift = relationship(
        "Shift",
        back_populates="roster_entries",
    )
