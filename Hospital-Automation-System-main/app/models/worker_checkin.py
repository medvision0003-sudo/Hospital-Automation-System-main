from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, func
from sqlalchemy.orm import relationship
from app.database.base import Base
from app.models.enums import CheckinStatusEnum


class WorkerCheckin(Base):
    __tablename__ = "worker_checkin"

    device_id = Column(String(50), primary_key=True)

    checkin_time = Column(
        DateTime,
        primary_key=True,
        server_default=func.now()
    )

    employee_id = Column(
        Integer,
        ForeignKey("employee.employee_id")
    )

    checkout_time = Column(DateTime)

    status = Column(Enum(CheckinStatusEnum), nullable=False)

    # Relationships
    employee = relationship(
        "Employee",
        back_populates="checkins"
    )