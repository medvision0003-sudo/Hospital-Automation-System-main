from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import DueOffsetEnum, PriorityEnum
from app.schemas.nursing_shift_log import NursingShiftLogResponse


class AutomationRecommendationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    recommendation_id: int
    pattern_key: str
    pattern_type: str
    description: str
    occurrences: int
    observations: int
    frequency: float
    confidence: float
    period_start: Optional[date]
    period_end: Optional[date]
    ward_area: Optional[str]
    shift_name: Optional[str]
    supporting_record_ids: list[int]
    suggested_action: str
    expected_benefit: str
    risk_level: str
    status: str
    reviewed_by: Optional[int]
    reviewed_at: Optional[datetime]
    review_notes: Optional[str]
    created_at: datetime
    updated_at: datetime


class AutomationRuleCreate(BaseModel):
    task_id: int = Field(..., gt=0)
    priority: Optional[PriorityEnum] = None
    due_offset: DueOffsetEnum = DueOffsetEnum.END_OF_DAY
    expires_at: Optional[datetime] = None
    review_notes: Optional[str] = Field(default=None, max_length=1000)


class AutomationRuleUpdate(BaseModel):
    task_id: Optional[int] = Field(default=None, gt=0)
    priority: Optional[PriorityEnum] = None
    due_offset: Optional[DueOffsetEnum] = None
    expires_at: Optional[datetime] = None
    ward_area: Optional[str] = Field(default=None, max_length=255)
    shift_name: Optional[str] = Field(default=None, max_length=100)
    review_notes: Optional[str] = Field(default=None, max_length=1000)


class AutomationReview(BaseModel):
    notes: Optional[str] = Field(default=None, max_length=1000)


class AutomationRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rule_id: int
    recommendation_id: int
    rule_name: str
    description: str
    trigger_type: str
    conditions: dict[str, Any]
    action_type: str
    action_config: dict[str, Any]
    status: str
    expires_at: Optional[datetime]
    created_by: Optional[int]
    approved_by: Optional[int]
    approved_employee_id: Optional[int]
    approved_at: Optional[datetime]
    disabled_by: Optional[int]
    disabled_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class AutomationRuleExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    execution_id: int
    rule_id: int
    source_key: str
    trigger_type: str
    source_report_id: Optional[int]
    status: str
    condition_results: dict[str, Any]
    result: Optional[dict[str, Any]]
    error_message: Optional[str]
    supervisor_task_request_id: Optional[int]
    started_at: datetime
    completed_at: Optional[datetime]


class AutomationRuleAuditResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    audit_id: int
    recommendation_id: Optional[int]
    rule_id: Optional[int]
    actor_id: Optional[int]
    action: str
    previous_state: Optional[dict[str, Any]]
    new_state: Optional[dict[str, Any]]
    notes: Optional[str]
    occurred_at: datetime


class PatternAnalysisResponse(BaseModel):
    reports_analyzed: int
    created: int
    updated: int
    recommendations: list[AutomationRecommendationResponse]


class RuleEffectivenessResponse(BaseModel):
    rule_id: int
    total_executions: int
    succeeded: int
    failed: int
    skipped: int
    pending: int
    success_rate: float
    request_processing_rate: Optional[float]
    executions: list[AutomationRuleExecutionResponse]


class ShiftReportSubmissionResponse(NursingShiftLogResponse):
    automation_executions: list[AutomationRuleExecutionResponse] = Field(default_factory=list)
