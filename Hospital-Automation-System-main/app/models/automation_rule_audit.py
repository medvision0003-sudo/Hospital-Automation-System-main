from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, func

from app.database.base import Base


class AutomationRuleAudit(Base):
    __tablename__ = "automation_rule_audit"

    audit_id = Column(Integer, primary_key=True)
    recommendation_id = Column(
        Integer,
        ForeignKey("automation_recommendation.recommendation_id"),
        nullable=True,
        index=True,
    )
    rule_id = Column(Integer, ForeignKey("automation_rule.rule_id"), nullable=True, index=True)
    actor_id = Column(Integer, ForeignKey("users.user_id"), nullable=True)
    action = Column(String(60), nullable=False)
    previous_state = Column(JSON, nullable=True)
    new_state = Column(JSON, nullable=True)
    notes = Column(Text, nullable=True)
    occurred_at = Column(DateTime, nullable=False, server_default=func.now())
