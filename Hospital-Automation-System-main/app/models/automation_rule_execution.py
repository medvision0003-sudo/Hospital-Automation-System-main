from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func

from app.database.base import Base


class AutomationRuleExecution(Base):
    __tablename__ = "automation_rule_execution"
    __table_args__ = (
        UniqueConstraint("rule_id", "source_key", name="uq_automation_execution_rule_source"),
    )

    execution_id = Column(Integer, primary_key=True)
    rule_id = Column(Integer, ForeignKey("automation_rule.rule_id"), nullable=False, index=True)
    source_key = Column(String(120), nullable=False)
    trigger_type = Column(String(60), nullable=False)
    source_report_id = Column(Integer, ForeignKey("nursing_shift_log.log_id"), nullable=True)
    status = Column(String(30), nullable=False, default="RUNNING", index=True)
    condition_results = Column(JSON, nullable=False)
    result = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    supervisor_task_request_id = Column(
        Integer,
        ForeignKey("supervisor_task_request.request_id"),
        nullable=True,
    )
    started_at = Column(DateTime, nullable=False, server_default=func.now())
    completed_at = Column(DateTime, nullable=True)
