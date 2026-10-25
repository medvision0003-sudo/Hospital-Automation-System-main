from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

from app.database.connection import get_db
from app.models.approval_request import ApprovalRequest
from app.models.orchestrator_trace import OrchestratorTrace

router = APIRouter(prefix="/approvals", tags=["Workflow Approval Gates"])


class ApprovalResponse(BaseModel):
    approval_id: int
    workflow_id: str
    sensitive_action: str
    rationale: Optional[str] = None
    status: str
    created_at: datetime
    resolved_at: Optional[datetime] = None
    supervisor_id: Optional[int] = None
    supervisor_notes: Optional[str] = None
    context_state_json: Optional[str] = None


class ApprovalActionRequest(BaseModel):
    supervisor_id: Optional[int] = None
    supervisor_notes: Optional[str] = None
    choice: Optional[str] = None
    overtime_duration: Optional[str] = None


def _build_approval_response(req: ApprovalRequest) -> ApprovalResponse:
    """Build a standardized ApprovalResponse from a DB row."""
    return ApprovalResponse(
        approval_id=req.approval_id,
        workflow_id=req.workflow_id,
        sensitive_action=req.sensitive_action,
        rationale=req.rationale,
        status=req.status,
        created_at=req.created_at,
        resolved_at=req.resolved_at,
        supervisor_id=req.supervisor_id,
        supervisor_notes=req.supervisor_notes,
        context_state_json=req.context_state_json,
    )


@router.get("/", response_model=List[ApprovalResponse])
def list_approvals(status_filter: Optional[str] = None, db: Session = Depends(get_db)):
    """List approval requests, optionally filtered by status."""
    query = db.query(ApprovalRequest).order_by(ApprovalRequest.created_at.desc())

    if status_filter:
        query = query.filter(ApprovalRequest.status == status_filter.upper())

    return [_build_approval_response(req) for req in query.all()]


@router.get("/{approval_id}", response_model=ApprovalResponse)
def get_approval(approval_id: int, db: Session = Depends(get_db)):
    """Get a single approval request detail."""
    req = db.query(ApprovalRequest).filter(
        ApprovalRequest.approval_id == approval_id
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return _build_approval_response(req)


@router.post("/{approval_id}/resume")
def resume_approval(approval_id: int, payload: ApprovalActionRequest, db: Session = Depends(get_db)):
    """Record supervisor approval and execute domain-specific resolution.

    For SHIFT_HANDOVER_REVIEW approvals:
        - choice="CHOICE_A" + overtime_duration: Grant overtime extension
        - choice="CHOICE_B": Preempt ASSIGNED tasks and carry forward

    For all other approvals: Standard approval recording.
    """
    req = db.query(ApprovalRequest).filter(
        ApprovalRequest.approval_id == approval_id
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="Approval request not found")

    if req.status != "PENDING":
        raise HTTPException(status_code=400, detail=f"Approval is already {req.status}")

    # Shift handover resolution dispatch
    if req.sensitive_action in ("SHIFT_HANDOVER_REVIEW", "EMERGENCY_OVERTIME_ASSIGNED"):
        from app.services.supervisor import (
            resolve_shift_handover_choice_a,
            resolve_shift_handover_choice_b,
        )

        choice = (payload.choice or "").upper()

        if choice == "CHOICE_A":
            overtime_duration = payload.overtime_duration or "ONE_HOUR"
            try:
                result = resolve_shift_handover_choice_a(approval_id, overtime_duration, db)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))

            # Record supervisor metadata
            req.supervisor_id = payload.supervisor_id
            req.supervisor_notes = payload.supervisor_notes
            db.commit()

            return {
                "message": "Overtime extension granted",
                "approval_id": approval_id,
                "status": "APPROVED",
                **result,
            }

        elif choice == "CHOICE_B":
            try:
                result = resolve_shift_handover_choice_b(approval_id, db)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))

            req.supervisor_id = payload.supervisor_id
            req.supervisor_notes = payload.supervisor_notes
            db.commit()

            return {
                "message": "Tasks preempted and carried forward",
                "approval_id": approval_id,
                "status": "RESOLVED",
                **result,
            }

        else:
            raise HTTPException(
                status_code=400,
                detail="SHIFT_HANDOVER_REVIEW requires choice='CHOICE_A' or 'CHOICE_B'"
            )

    # Standard approval path (non-handover)
    req.status = "APPROVED"
    req.resolved_at = datetime.now()
    req.supervisor_id = payload.supervisor_id
    req.supervisor_notes = payload.supervisor_notes

    # Update the associated orchestrator trace
    trace = db.query(OrchestratorTrace).filter(
        OrchestratorTrace.workflow_id == req.workflow_id
    ).first()
    if trace:
        trace.execution_status = "APPROVED"

    db.commit()

    # Record supervisor override experience
    try:
        from app.services.workflow_experience_service import record_workflow_experience
        from app.orchestrator.constants import ResolutionType
        record_workflow_experience(
            db=db,
            event_type=req.sensitive_action,
            resolution_type=ResolutionType.SUPERVISOR_OVERRIDE,
            workflow_id=req.workflow_id,
            resolution_action="APPROVAL_GRANTED",
            metadata_extra={"approval_id": approval_id},
        )
        db.commit()
    except Exception:
        pass

    return {
        "message": "Approval recorded successfully",
        "approval_id": approval_id,
        "status": "APPROVED",
    }


@router.post("/{approval_id}/reject")
def reject_approval(approval_id: int, payload: ApprovalActionRequest, db: Session = Depends(get_db)):
    """Reject the approval request and mark the associated workflow as FAILED."""
    req = db.query(ApprovalRequest).filter(
        ApprovalRequest.approval_id == approval_id
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="Approval request not found")

    if req.status != "PENDING":
        raise HTTPException(status_code=400, detail=f"Approval is already {req.status}")

    req.status = "REJECTED"
    req.resolved_at = datetime.now()
    req.supervisor_id = payload.supervisor_id
    req.supervisor_notes = payload.supervisor_notes

    trace = db.query(OrchestratorTrace).filter(
        OrchestratorTrace.workflow_id == req.workflow_id
    ).first()
    if trace:
        trace.execution_status = "FAILED"
        trace.error_message = f"Approval rejected by supervisor: {payload.supervisor_notes or 'No reason provided'}"

    db.commit()

    # Record supervisor override experience
    try:
        from app.services.workflow_experience_service import record_workflow_experience
        from app.orchestrator.constants import ResolutionType
        record_workflow_experience(
            db=db,
            event_type=req.sensitive_action,
            resolution_type=ResolutionType.SUPERVISOR_OVERRIDE,
            workflow_id=req.workflow_id,
            resolution_action="APPROVAL_REJECTED",
            metadata_extra={"approval_id": approval_id},
        )
        db.commit()
    except Exception:
        pass

    return {
        "message": "Approval rejected",
        "approval_id": approval_id,
        "status": "REJECTED",
    }
