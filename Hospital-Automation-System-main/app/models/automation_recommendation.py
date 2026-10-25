from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text, func

from app.database.base import Base


class AutomationRecommendation(Base):
    __tablename__ = "automation_recommendation"

    recommendation_id = Column(Integer, primary_key=True)
    pattern_key = Column(String(64), nullable=False, unique=True, index=True)
    pattern_type = Column(String(60), nullable=False, index=True)
    description = Column(Text, nullable=False)
    occurrences = Column(Integer, nullable=False)
    observations = Column(Integer, nullable=False)
    frequency = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    period_start = Column(Date, nullable=True)
    period_end = Column(Date, nullable=True)
    ward_area = Column(String(255), nullable=True)
    shift_name = Column(String(100), nullable=True)
    supporting_record_ids = Column(JSON, nullable=False)
    suggested_action = Column(String(60), nullable=False)
    expected_benefit = Column(Text, nullable=False)
    risk_level = Column(String(30), nullable=False)
    status = Column(String(30), nullable=False, default="PENDING_APPROVAL", index=True)
    reviewed_by = Column(Integer, ForeignKey("users.user_id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    review_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
