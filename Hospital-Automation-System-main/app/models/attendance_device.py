from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, func

from app.database.base import Base


class AttendanceDevice(Base):
    __tablename__ = "attendance_device"

    device_id = Column(String(100), primary_key=True)
    employee_id = Column(
        ForeignKey("employee.employee_id"),
        nullable=False,
        index=True,
    )
    token_hash = Column(String(64), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    last_seen_at = Column(DateTime, nullable=True)
