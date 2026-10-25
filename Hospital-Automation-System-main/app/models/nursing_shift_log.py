from sqlalchemy import Column, Date, DateTime, Integer, JSON, String, UniqueConstraint

from app.database.base import Base


class NursingShiftLog(Base):
    __tablename__ = "nursing_shift_log"
    __table_args__ = (
        UniqueConstraint("source_hash", name="uq_nursing_shift_log_source_hash"),
    )

    log_id = Column(Integer, primary_key=True, autoincrement=True)
    source_hash = Column(String(64), nullable=False)
    submitted_at = Column(DateTime, nullable=False)
    nurse_name = Column(String(255), nullable=False, index=True)
    shift_date = Column(Date, nullable=False, index=True)
    shift_name = Column(String(100), nullable=False)
    ward_area = Column(String(255), nullable=False)
    answers = Column(JSON, nullable=False)
