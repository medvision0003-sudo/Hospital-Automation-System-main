from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, func

from app.database.base import Base


class AutomationRule(Base):
    __tablename__ = "automation_rule"

    rule_id = Column(Integer, primary_key=True)
    recommendation_id = Column(
        Integer,
        ForeignKey("automation_recommendation.recommendation_id"),
        nullable=False,
        unique=True,
    )
    rule_name = Column(String(120), nullable=False, unique=True)
    description = Column(Text, nullable=False)
    trigger_type = Column(String(60), nullable=False)
    conditions = Column(JSON, nullable=False)
    action_type = Column(String(60), nullable=False)
    action_config = Column(JSON, nullable=False)
    status = Column(String(30), nullable=False, default="PENDING_APPROVAL", index=True)
    expires_at = Column(DateTime, nullable=True)
    created_by = Column(Integer, ForeignKey("users.user_id"), nullable=True)
    approved_by = Column(Integer, ForeignKey("users.user_id"), nullable=True)
    approved_employee_id = Column(Integer, ForeignKey("employee.employee_id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    disabled_by = Column(Integer, ForeignKey("users.user_id"), nullable=True)
    disabled_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
