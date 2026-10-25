import logging
from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.pattern_learning_agent import PatternLearningAgent
from app.models.automation_recommendation import AutomationRecommendation
from app.models.automation_rule import AutomationRule
from app.models.automation_rule_audit import AutomationRuleAudit
from app.models.automation_rule_execution import AutomationRuleExecution
from app.models.enums import (
    DueOffsetEnum,
    EmploymentStatusEnum,
    PriorityEnum,
    TaskStatusEnum,
)
from app.models.employee import Employee
from app.models.nursing_shift_log import NursingShiftLog
from app.models.supervisor_task_request import SupervisorTaskRequest
from app.models.task_master import TaskMaster
from app.models.user import User
from app.schemas.supervisor_task_request import SupervisorTaskRequestCreate
from app.services.supervisor import create_supervisor_request

logger = logging.getLogger(__name__)

RULE_ACTION = "CREATE_SUPERVISOR_TASK_REQUEST"
RULE_TRIGGER = "SHIFT_REPORT_SUBMITTED"


def _state(value: Any) -> dict:
    if value is None:
        return {}
    return {
        "status": value.status,
        "conditions": value.conditions if hasattr(value, "conditions") else None,
        "action_config": value.action_config if hasattr(value, "action_config") else None,
        "approved_by": value.approved_by if hasattr(value, "approved_by") else None,
        "approved_employee_id": (
            value.approved_employee_id if hasattr(value, "approved_employee_id") else None
        ),
        "disabled_by": value.disabled_by if hasattr(value, "disabled_by") else None,
    }


def _audit(
    db: Session,
    *,
    actor_id: int | None,
    action: str,
    recommendation_id: int | None = None,
    rule_id: int | None = None,
    previous_state: dict | None = None,
    new_state: dict | None = None,
    notes: str | None = None,
) -> None:
    db.add(
        AutomationRuleAudit(
            actor_id=actor_id,
            action=action,
            recommendation_id=recommendation_id,
            rule_id=rule_id,
            previous_state=previous_state,
            new_state=new_state,
            notes=notes,
        )
    )


def _active_task(db: Session, task_id: int) -> TaskMaster | None:
    return (
        db.query(TaskMaster)
        .filter(
            TaskMaster.task_id == task_id,
            TaskMaster.task_state == TaskStatusEnum.ACTIVE,
        )
        .first()
    )


def _actor_employee_id(db: Session, actor_id: int) -> int | None:
    actor = db.query(User).filter(User.user_id == actor_id, User.is_active.is_(True)).first()
    return actor.employee_id if actor else None


def create_rule_from_recommendation(
    db: Session,
    recommendation: AutomationRecommendation,
    *,
    task_id: int,
    priority: PriorityEnum | None,
    due_offset: DueOffsetEnum,
    expires_at: datetime | None,
    actor_id: int,
    notes: str | None,
) -> AutomationRule:
    if recommendation.status != "PENDING_APPROVAL":
        raise ValueError("Only pending recommendations can be converted into rules.")
    if not _active_task(db, task_id):
        raise ValueError("The selected task template does not exist or is inactive.")
    existing = (
        db.query(AutomationRule)
        .filter(AutomationRule.recommendation_id == recommendation.recommendation_id)
        .first()
    )
    if existing:
        return existing

    rule = AutomationRule(
        recommendation_id=recommendation.recommendation_id,
        rule_name=f"LEARNED-{recommendation.pattern_type}-{recommendation.recommendation_id}",
        description=recommendation.description,
        trigger_type=RULE_TRIGGER,
        conditions={
            "signal_type": recommendation.pattern_type,
            "ward_area": recommendation.ward_area,
            "shift_name": recommendation.shift_name,
        },
        action_type=RULE_ACTION,
        action_config={
            "task_id": task_id,
            "priority": priority.value if priority else None,
            "due_offset": due_offset.value,
        },
        status="PENDING_APPROVAL",
        expires_at=expires_at,
        created_by=actor_id,
    )
    db.add(rule)
    db.flush()
    _audit(
        db,
        actor_id=actor_id,
        action="RULE_CREATED_PENDING_APPROVAL",
        recommendation_id=recommendation.recommendation_id,
        rule_id=rule.rule_id,
        new_state=_state(rule),
        notes=notes,
    )
    db.commit()
    db.refresh(rule)
    return rule


def update_pending_rule(
    db: Session,
    rule: AutomationRule,
    changes: dict,
    *,
    actor_id: int,
) -> AutomationRule:
    if rule.status != "PENDING_APPROVAL":
        raise ValueError("Only pending rules can be edited.")
    previous = _state(rule)
    if "task_id" in changes:
        if not _active_task(db, changes["task_id"]):
            raise ValueError("The selected task template does not exist or is inactive.")
        action_config = dict(rule.action_config)
        action_config["task_id"] = changes.pop("task_id")
        rule.action_config = action_config
    if "priority" in changes:
        priority = changes.pop("priority")
        action_config = dict(rule.action_config)
        action_config["priority"] = priority.value if priority else None
        rule.action_config = action_config
    if "due_offset" in changes:
        due_offset = changes.pop("due_offset")
        action_config = dict(rule.action_config)
        action_config["due_offset"] = due_offset.value
        rule.action_config = action_config
    if "ward_area" in changes:
        conditions = dict(rule.conditions)
        conditions["ward_area"] = changes.pop("ward_area")
        rule.conditions = conditions
    if "shift_name" in changes:
        conditions = dict(rule.conditions)
        conditions["shift_name"] = changes.pop("shift_name")
        rule.conditions = conditions
    if "expires_at" in changes:
        rule.expires_at = changes.pop("expires_at")
    notes = changes.pop("review_notes", None)
    _audit(
        db,
        actor_id=actor_id,
        action="RULE_EDITED",
        recommendation_id=rule.recommendation_id,
        rule_id=rule.rule_id,
        previous_state=previous,
        new_state=_state(rule),
        notes=notes,
    )
    db.commit()
    db.refresh(rule)
    return rule


def approve_rule(
    db: Session,
    rule: AutomationRule,
    *,
    actor_id: int,
    notes: str | None,
) -> AutomationRule:
    if rule.status != "PENDING_APPROVAL":
        raise ValueError("Only pending rules can be approved.")
    employee_id = _actor_employee_id(db, actor_id)
    if employee_id is None:
        raise ValueError(
            "Rule approval requires an active user linked to an employee record "
            "so the existing supervisor workflow has a valid supervisor identity."
        )
    task_id = rule.action_config.get("task_id")
    if not _active_task(db, task_id):
        raise ValueError("The rule task template does not exist or is inactive.")
    if rule.expires_at and rule.expires_at <= datetime.now():
        raise ValueError("An expired rule cannot be approved.")

    recommendation = (
        db.query(AutomationRecommendation)
        .filter(AutomationRecommendation.recommendation_id == rule.recommendation_id)
        .first()
    )
    before = _state(rule)
    rule.approved_by = actor_id
    rule.approved_employee_id = employee_id
    rule.approved_at = datetime.now()
    rule.status = "ACTIVE"
    if recommendation:
        recommendation.status = "APPROVED"
        recommendation.reviewed_by = actor_id
        recommendation.reviewed_at = rule.approved_at
        recommendation.review_notes = notes

    _audit(
        db,
        actor_id=actor_id,
        action="RULE_APPROVED",
        recommendation_id=rule.recommendation_id,
        rule_id=rule.rule_id,
        previous_state=before,
        new_state=_state(rule),
        notes=notes,
    )
    _audit(
        db,
        actor_id=actor_id,
        action="RULE_ACTIVATED",
        recommendation_id=rule.recommendation_id,
        rule_id=rule.rule_id,
        previous_state={"status": "APPROVED"},
        new_state={"status": rule.status},
        notes=notes,
    )
    db.commit()
    db.refresh(rule)
    return rule


def reject_rule(
    db: Session,
    rule: AutomationRule,
    *,
    actor_id: int,
    notes: str | None,
) -> AutomationRule:
    if rule.status != "PENDING_APPROVAL":
        raise ValueError("Only pending rules can be rejected.")
    before = _state(rule)
    rule.status = "REJECTED"
    recommendation = (
        db.query(AutomationRecommendation)
        .filter(AutomationRecommendation.recommendation_id == rule.recommendation_id)
        .first()
    )
    if recommendation:
        recommendation.status = "REJECTED"
        recommendation.reviewed_by = actor_id
        recommendation.reviewed_at = datetime.now()
        recommendation.review_notes = notes
    _audit(
        db,
        actor_id=actor_id,
        action="RULE_REJECTED",
        recommendation_id=rule.recommendation_id,
        rule_id=rule.rule_id,
        previous_state=before,
        new_state=_state(rule),
        notes=notes,
    )
    db.commit()
    db.refresh(rule)
    return rule


def reject_recommendation(
    db: Session,
    recommendation: AutomationRecommendation,
    *,
    actor_id: int,
    notes: str | None,
) -> AutomationRecommendation:
    if recommendation.status != "PENDING_APPROVAL":
        raise ValueError("Only pending recommendations can be rejected.")
    pending_rule = (
        db.query(AutomationRule)
        .filter(
            AutomationRule.recommendation_id == recommendation.recommendation_id,
            AutomationRule.status == "PENDING_APPROVAL",
        )
        .first()
    )
    if pending_rule:
        previous = _state(pending_rule)
        pending_rule.status = "REJECTED"
        _audit(
            db,
            actor_id=actor_id,
            action="RULE_REJECTED_WITH_RECOMMENDATION",
            recommendation_id=recommendation.recommendation_id,
            rule_id=pending_rule.rule_id,
            previous_state=previous,
            new_state=_state(pending_rule),
            notes=notes,
        )
    recommendation.status = "REJECTED"
    recommendation.reviewed_by = actor_id
    recommendation.reviewed_at = datetime.now()
    recommendation.review_notes = notes
    _audit(
        db,
        actor_id=actor_id,
        action="RECOMMENDATION_REJECTED",
        recommendation_id=recommendation.recommendation_id,
        previous_state={"status": "PENDING_APPROVAL"},
        new_state={"status": recommendation.status},
        notes=notes,
    )
    db.commit()
    db.refresh(recommendation)
    return recommendation


def expire_rules(db: Session, *, actor_id: int) -> int:
    now = datetime.now()
    expired_rules = (
        db.query(AutomationRule)
        .filter(
            AutomationRule.status == "ACTIVE",
            AutomationRule.expires_at.isnot(None),
            AutomationRule.expires_at <= now,
        )
        .all()
    )
    for rule in expired_rules:
        previous = _state(rule)
        rule.status = "EXPIRED"
        _audit(
            db,
            actor_id=actor_id,
            action="RULE_EXPIRED",
            recommendation_id=rule.recommendation_id,
            rule_id=rule.rule_id,
            previous_state=previous,
            new_state=_state(rule),
            notes="Expired rule sweep.",
        )
    db.commit()
    return len(expired_rules)


def disable_rule(
    db: Session,
    rule: AutomationRule,
    *,
    actor_id: int,
    notes: str | None,
) -> AutomationRule:
    if rule.status != "ACTIVE":
        raise ValueError("Only active rules can be disabled.")
    previous = _state(rule)
    rule.status = "DISABLED"
    rule.disabled_by = actor_id
    rule.disabled_at = datetime.now()
    _audit(
        db,
        actor_id=actor_id,
        action="RULE_DISABLED",
        recommendation_id=rule.recommendation_id,
        rule_id=rule.rule_id,
        previous_state=previous,
        new_state=_state(rule),
        notes=notes,
    )
    db.commit()
    db.refresh(rule)
    return rule


def execute_rules_for_report(db: Session, report: NursingShiftLog) -> list[AutomationRuleExecution]:
    rules = (
        db.query(AutomationRule)
        .filter(
            AutomationRule.status == "ACTIVE",
            AutomationRule.trigger_type == RULE_TRIGGER,
            AutomationRule.action_type == RULE_ACTION,
        )
        .order_by(AutomationRule.rule_id.asc())
        .all()
    )
    results = []
    source_key = f"SHIFT_REPORT:{report.log_id}"
    now = datetime.now()
    for rule in rules:
        matches, checks = PatternLearningAgent.matches(report, rule.conditions or {})
        if not matches:
            continue
        prior = (
            db.query(AutomationRuleExecution)
            .filter(
                AutomationRuleExecution.rule_id == rule.rule_id,
                AutomationRuleExecution.source_key == source_key,
            )
            .first()
        )
        if prior:
            results.append(prior)
            continue
        if rule.expires_at and rule.expires_at <= now:
            before = _state(rule)
            rule.status = "EXPIRED"
            _audit(
                db,
                actor_id=None,
                action="RULE_EXPIRED",
                recommendation_id=rule.recommendation_id,
                rule_id=rule.rule_id,
                previous_state=before,
                new_state=_state(rule),
                notes="Expired before matching report execution.",
            )
            db.commit()
            continue

        execution = AutomationRuleExecution(
            rule_id=rule.rule_id,
            source_key=source_key,
            trigger_type=RULE_TRIGGER,
            source_report_id=report.log_id,
            status="RUNNING",
            condition_results=checks,
        )
        db.add(execution)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            prior = (
                db.query(AutomationRuleExecution)
                .filter(
                    AutomationRuleExecution.rule_id == rule.rule_id,
                    AutomationRuleExecution.source_key == source_key,
                )
                .first()
            )
            if prior is None:
                raise
            results.append(prior)
            continue
        db.refresh(execution)

        try:
            supervisor = (
                db.query(Employee)
                .filter(
                    Employee.employee_id == rule.approved_employee_id,
                    Employee.availability == EmploymentStatusEnum.ACTIVE,
                )
                .first()
            )
            if supervisor is None:
                raise ValueError("The approving supervisor employee record is no longer active.")
            task_id = rule.action_config["task_id"]
            if not _active_task(db, task_id):
                raise ValueError("The rule task template is no longer active.")
            priority_value = rule.action_config.get("priority")
            priority = PriorityEnum(priority_value) if priority_value else None
            due_offset = DueOffsetEnum(rule.action_config["due_offset"])
            request = create_supervisor_request(
                db,
                SupervisorTaskRequestCreate(
                    task_id=task_id,
                    supervisor_id=supervisor.employee_id,
                    priority=priority,
                    due_offset=due_offset,
                    remarks=(
                        f"Approved automation rule {rule.rule_name} matched "
                        f"shift report {report.log_id}. Review using established workflows."
                    ),
                ),
            )
            execution.status = "SUCCEEDED"
            execution.supervisor_task_request_id = request.request_id
            execution.result = {
                "request_id": request.request_id,
                "dispatch_status": "QUEUED_FOR_EXISTING_ORCHESTRATOR",
                "meaning": "A supervisor task request was created; downstream completion is tracked separately.",
            }
        except Exception as exc:
            logger.exception(
                "Approved staff automation rule %s failed for shift report %s",
                rule.rule_id,
                report.log_id,
            )
            db.rollback()
            execution = (
                db.query(AutomationRuleExecution)
                .filter(AutomationRuleExecution.execution_id == execution.execution_id)
                .first()
            )
            if execution is None:
                raise
            execution.status = "FAILED"
            execution.error_message = str(exc)
            execution.result = {"dispatch_status": "FAILED"}
        execution.completed_at = datetime.now()
        db.commit()
        db.refresh(execution)
        results.append(execution)
    return results


def rule_effectiveness(db: Session, rule_id: int) -> dict:
    executions = (
        db.query(AutomationRuleExecution)
        .filter(AutomationRuleExecution.rule_id == rule_id)
        .order_by(AutomationRuleExecution.started_at.desc())
        .all()
    )
    counts = {
        "SUCCEEDED": 0,
        "FAILED": 0,
        "SKIPPED": 0,
        "RUNNING": 0,
    }
    request_ids = []
    for execution in executions:
        if execution.status in counts:
            counts[execution.status] += 1
        if execution.supervisor_task_request_id:
            request_ids.append(execution.supervisor_task_request_id)
    processed = 0
    if request_ids:
        processed = (
            db.query(SupervisorTaskRequest)
            .filter(
                SupervisorTaskRequest.request_id.in_(request_ids),
                SupervisorTaskRequest.processed_at.isnot(None),
            )
            .count()
        )
    success_rate = counts["SUCCEEDED"] / len(executions) if executions else 0.0
    processing_rate = processed / len(request_ids) if request_ids else None
    return {
        "rule_id": rule_id,
        "total_executions": len(executions),
        "succeeded": counts["SUCCEEDED"],
        "failed": counts["FAILED"],
        "skipped": counts["SKIPPED"],
        "pending": counts["RUNNING"],
        "success_rate": success_rate,
        "request_processing_rate": processing_rate,
        "executions": executions,
    }
