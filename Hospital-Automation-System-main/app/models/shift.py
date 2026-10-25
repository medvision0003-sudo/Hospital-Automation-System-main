from sqlalchemy import Column, Integer, String, Time, ForeignKey
from sqlalchemy.orm import relationship

from app.database.base import Base


class Shift(Base):
    __tablename__ = "shift"

    shift_id = Column(Integer, primary_key=True, autoincrement=True)

    department_id = Column(
        Integer,
        ForeignKey("department.department_id"),
        nullable=True,
    )

    shift_name = Column(String(100), nullable=False)

    start_time = Column(Time, nullable=False)

    end_time = Column(Time, nullable=False)

    # Relationships
    department = relationship(
        "Department",
        back_populates="shifts",
    )

    # ShiftRoster maps to the "shift_scheduler" table, representing scheduler entries
    roster_entries = relationship(
        "ShiftRoster",
        back_populates="shift",
        cascade="all, delete-orphan",
    )
