from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.agents.pattern_learning_agent import PatternLearningAgent
from app.core.dependencies import get_current_user
from app.database.connection import get_db
from app.models.automation_recommendation import AutomationRecommendation
from app.models.automation_rule import AutomationRule
from app.models.automation_rule_audit import AutomationRuleAudit
from app.models.automation_rule_execution import AutomationRuleExecution
from app.models.user import User
from app.schemas.staff_automation import (
    AutomationRecommendationResponse,
    AutomationReview,
    AutomationRuleAuditResponse,
    AutomationRuleCreate,
    AutomationRuleExecutionResponse,
    AutomationRuleResponse,
    AutomationRuleUpdate,
    PatternAnalysisResponse,
    RuleEffectivenessResponse,
)
from app.services.staff_automation_rules import (
    approve_rule,
    create_rule_from_recommendation,
    disable_rule,
    expire_rules,
    reject_recommendation,
    reject_rule,
    rule_effectiveness,
    update_pending_rule,
)

router = APIRouter(prefix="/staff-automation", tags=["Staff Automation - Learned Rules"])

RECOMMENDATION_STATES = {
    "PENDING_APPROVAL",
    "APPROVED",
    "REJECTED",
}
RULE_STATES = {
    "PENDING_APPROVAL",
    "ACTIVE",
    "REJECTED",
    "DISABLED",
    "EXPIRED",
}


def _not_found(message: str) -> HTTPException:
    return HTTPException(status_code=404, detail=message)


def _bad_request(error: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(error))


@router.post("/pattern-learning/analyze", response_model=PatternAnalysisResponse)
def analyze_patterns(
    db: Session = Depends(get_db),
):
    return PatternLearningAgent().analyze(db)


@router.get("/recommendations", response_model=list[AutomationRecommendationResponse])
def list_recommendations(
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(AutomationRecommendation)
    if status:
        normalized = status.upper()
        if normalized not in RECOMMENDATION_STATES:
            raise HTTPException(status_code=400, detail="Unsupported recommendation status.")
        query = query.filter(AutomationRecommendation.status == normalized)
    return query.order_by(AutomationRecommendation.created_at.desc()).limit(limit).all()


@router.post(
    "/recommendations/{recommendation_id}/rules",
    response_model=AutomationRuleResponse,
)
def create_recommendation_rule(
    recommendation_id: int,
    data: AutomationRuleCreate,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    recommendation = (
        db.query(AutomationRecommendation)
        .filter(AutomationRecommendation.recommendation_id == recommendation_id)
        .first()
    )
    if recommendation is None:
        raise _not_found("Automation recommendation not found.")
    existing = (
        db.query(AutomationRule)
        .filter(AutomationRule.recommendation_id == recommendation_id)
        .first()
    )
    response.status_code = 200 if existing else 201
    try:
        return create_rule_from_recommendation(
            db,
            recommendation,
            task_id=data.task_id,
            priority=data.priority,
            due_offset=data.due_offset,
            expires_at=data.expires_at,
            actor_id=current_user.user_id,
            notes=data.review_notes,
        )
    except ValueError as error:
        raise _bad_request(error) from error


@router.post(
    "/recommendations/{recommendation_id}/reject",
    response_model=AutomationRecommendationResponse,
)
def reject_pending_recommendation(
    recommendation_id: int,
    data: AutomationReview,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    recommendation = (
        db.query(AutomationRecommendation)
        .filter(AutomationRecommendation.recommendation_id == recommendation_id)
        .first()
    )
    if recommendation is None:
        raise _not_found("Automation recommendation not found.")
    try:
        return reject_recommendation(
            db,
            recommendation,
            actor_id=current_user.user_id,
            notes=data.notes,
        )
    except ValueError as error:
        raise _bad_request(error) from error


@router.get("/rules", response_model=list[AutomationRuleResponse])
def list_rules(
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(AutomationRule)
    if status:
        normalized = status.upper()
        if normalized not in RULE_STATES:
            raise HTTPException(status_code=400, detail="Unsupported rule status.")
        query = query.filter(AutomationRule.status == normalized)
    return query.order_by(AutomationRule.created_at.desc()).limit(limit).all()


@router.post("/rules/expire")
def expire_due_rules(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return {"expired": expire_rules(db, actor_id=current_user.user_id)}


@router.put("/rules/{rule_id}", response_model=AutomationRuleResponse)
def edit_pending_rule(
    rule_id: int,
    data: AutomationRuleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rule = db.query(AutomationRule).filter(AutomationRule.rule_id == rule_id).first()
    if rule is None:
        raise _not_found("Automation rule not found.")
    try:
        return update_pending_rule(
            db,
            rule,
            data.model_dump(exclude_unset=True),
            actor_id=current_user.user_id,
        )
    except ValueError as error:
        raise _bad_request(error) from error


@router.post("/rules/{rule_id}/approve", response_model=AutomationRuleResponse)
def approve_pending_rule(
    rule_id: int,
    data: AutomationReview,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rule = db.query(AutomationRule).filter(AutomationRule.rule_id == rule_id).first()
    if rule is None:
        raise _not_found("Automation rule not found.")
    try:
        return approve_rule(
            db,
            rule,
            actor_id=current_user.user_id,
            notes=data.notes,
        )
    except ValueError as error:
        raise _bad_request(error) from error


@router.post("/rules/{rule_id}/reject", response_model=AutomationRuleResponse)
def reject_pending_rule(
    rule_id: int,
    data: AutomationReview,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rule = db.query(AutomationRule).filter(AutomationRule.rule_id == rule_id).first()
    if rule is None:
        raise _not_found("Automation rule not found.")
    try:
        return reject_rule(
            db,
            rule,
            actor_id=current_user.user_id,
            notes=data.notes,
        )
    except ValueError as error:
        raise _bad_request(error) from error


@router.post("/rules/{rule_id}/disable", response_model=AutomationRuleResponse)
def disable_active_rule(
    rule_id: int,
    data: AutomationReview,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rule = db.query(AutomationRule).filter(AutomationRule.rule_id == rule_id).first()
    if rule is None:
        raise _not_found("Automation rule not found.")
    try:
        return disable_rule(
            db,
            rule,
            actor_id=current_user.user_id,
            notes=data.notes,
        )
    except ValueError as error:
        raise _bad_request(error) from error


@router.get(
    "/rules/{rule_id}/executions",
    response_model=list[AutomationRuleExecutionResponse],
)
def list_rule_executions(
    rule_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    if db.query(AutomationRule.rule_id).filter(AutomationRule.rule_id == rule_id).first() is None:
        raise _not_found("Automation rule not found.")
    return (
        db.query(AutomationRuleExecution)
        .filter(AutomationRuleExecution.rule_id == rule_id)
        .order_by(AutomationRuleExecution.started_at.desc())
        .limit(limit)
        .all()
    )


@router.get("/rules/{rule_id}/effectiveness", response_model=RuleEffectivenessResponse)
def get_rule_effectiveness(rule_id: int, db: Session = Depends(get_db)):
    if db.query(AutomationRule.rule_id).filter(AutomationRule.rule_id == rule_id).first() is None:
        raise _not_found("Automation rule not found.")
    return rule_effectiveness(db, rule_id)


@router.get("/audit", response_model=list[AutomationRuleAuditResponse])
def list_rule_audit(
    rule_id: Optional[int] = Query(default=None, gt=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(AutomationRuleAudit)
    if rule_id is not None:
        query = query.filter(AutomationRuleAudit.rule_id == rule_id)
    return query.order_by(AutomationRuleAudit.occurred_at.desc()).limit(limit).all()
