import re
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime, timedelta

from app.database.connection import get_db
from app.core.dependencies import get_current_user
from app.models.agent_action_log import AgentActionLog
from app.models.approval_request import ApprovalRequest
from app.models.department import Department
from app.models.department_work_queue import DepartmentWorkQueue
from app.models.task_assignment import TaskAssignment
from app.models.task_proof import TaskProof
from app.models.event_log import EventLog
from app.models.worker_memory import WorkerMemory
from app.models.employee import Employee
from app.models.user import User
from app.models.enums import (
    AgentActionStatusEnum,
    WorkQueueStatusEnum,
    AssignmentStatusEnum,
    TaskProofStatusEnum,
    UserRoleEnum,
)

router = APIRouter(prefix="/escalations", tags=["Escalations & Human in the Loop"])


# Response and request schemas

class EscalationResponse(BaseModel):
    source_type: str
    source_id: int
    event_id: Optional[int] = None
    department_id: Optional[int] = None
    department_name: Optional[str] = "N/A"
    action_type: str
    execution_status: str
    decision_summary: Optional[str] = None
    action_timestamp: datetime
    is_resolved: bool
    resolved_at: Optional[datetime] = None
    supervisor_id: Optional[int] = None
    supervisor_notes: Optional[str] = None
    resolution_action: Optional[str] = None
    proof_id: Optional[int] = None
    proof_image_path: Optional[str] = None
    proof_employee_id: Optional[int] = None
    work_id: Optional[int] = None
    task_name: Optional[str] = None
    verification_status: Optional[str] = None
    ai_decision: Optional[str] = None
    verification_confidence: Optional[float] = None
    verification_rationale: Optional[str] = None
    verification_attempts: Optional[int] = None
    context_state_json: Optional[str] = None
    workflow_id: Optional[str] = None


# Backend deadline preset mapping
DEADLINE_PRESETS = {
    "PLUS_1_HOUR": 1,
    "PLUS_2_HOURS": 2,
    "PLUS_4_HOURS": 4,
    "PLUS_8_HOURS": 8,
}


class ResolveEscalationRequest(BaseModel):
    resolution_notes: Optional[str] = None
    resolution_action: str = "RESOLVE"
    assigned_employee_id: Optional[int] = None
    work_id: Optional[int] = None
    proof_id: Optional[int] = None
    rejection_reason: Optional[str] = None
    extend_hours: Optional[int] = None
    extend_preset: Optional[str] = None
    supervisor_id: Optional[int] = None
    selected_work_ids: Optional[List[int]] = None


# Escalation type filters
ESCALATION_ACTION_TYPES = (
    "ESCALATION",
    "PROOF_REVIEW_REQUIRED",
)


@router.get("/", response_model=List[EscalationResponse])
def list_escalations(
    response: Response,
    status_filter: Optional[str] = None,
    limit: Optional[int] = Query(default=None, ge=1, le=250),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Unified escalation listing from AgentActionLog and ApprovalRequest sources."""

    results = []

    # Source 1: AgentActionLog escalation-type rows
    agent_filter = (
        (AgentActionLog.action_type.in_(ESCALATION_ACTION_TYPES)) |
        (AgentActionLog.execution_status == AgentActionStatusEnum.FAILED) |
        (AgentActionLog.decision_summary.like("%HUMAN_REVIEW_REQUIRED%")) |
        (AgentActionLog.decision_summary.like("%ESCALATION%"))
    )
    agent_base_query = db.query(AgentActionLog).filter(agent_filter)
    approval_base_query = db.query(ApprovalRequest)
    if current_user.role == UserRoleEnum.SUPERVISOR:
        agent_base_query = agent_base_query.filter(
            AgentActionLog.department_id == current_user.department_id
        )
        approval_base_query = approval_base_query.filter(False)

    total_count = agent_base_query.count() + approval_base_query.count()
    pending_count = (
        agent_base_query.filter(
            or_(AgentActionLog.is_resolved.is_(False), AgentActionLog.is_resolved.is_(None))
        ).count()
        + approval_base_query.filter(ApprovalRequest.status == "PENDING").count()
    )
    resolved_count = (
        agent_base_query.filter(AgentActionLog.is_resolved.is_(True)).count()
        + approval_base_query.filter(ApprovalRequest.status != "PENDING").count()
    )

    agent_query = agent_base_query
    approval_query = approval_base_query
    if status_filter == "PENDING":
        agent_query = agent_query.filter(
            or_(AgentActionLog.is_resolved.is_(False), AgentActionLog.is_resolved.is_(None))
        )
        approval_query = approval_query.filter(ApprovalRequest.status == "PENDING")
    elif status_filter == "RESOLVED":
        agent_query = agent_query.filter(AgentActionLog.is_resolved.is_(True))
        approval_query = approval_query.filter(ApprovalRequest.status != "PENDING")

    agent_query = agent_query.order_by(AgentActionLog.action_timestamp.desc())
    approval_query = approval_query.order_by(ApprovalRequest.created_at.desc())
    if limit is not None:
        fetch_count = offset + limit
        agent_query = agent_query.limit(fetch_count)
        approval_query = approval_query.limit(fetch_count)

    for act in agent_query.all():
        resolved = act.is_resolved if act.is_resolved is not None else False

        dept_name = _resolve_department_name(act.department_id, act.decision_summary, db)

        formatted_summary = _format_summary(act.decision_summary or "")

        proof_id = None
        proof_image_path = None
        proof_employee_id = None
        task_name = None
        verification_status = None
        ai_decision = None
        verification_confidence = None
        verification_rationale = None
        verification_attempts = None
        work_id = _extract_work_id(act, db)
        if work_id:
            work_item = db.query(DepartmentWorkQueue).filter(
                DepartmentWorkQueue.work_id == work_id
            ).first()
            if work_item and work_item.task:
                task_name = work_item.task.task_name
            proof_record = _get_proof_for_action(act, db)
            if proof_record:
                proof_id = proof_record.proof_id
                proof_image_path = proof_record.proof_image_path
                proof_employee_id = proof_record.employee_id
                verification_status = (
                    proof_record.verification_status.value
                    if hasattr(proof_record.verification_status, "value")
                    else str(proof_record.verification_status)
                )
                ai_decision = proof_record.ai_decision
                verification_confidence = proof_record.verification_confidence
                verification_rationale = proof_record.verification_rationale
                verification_attempts = proof_record.verification_attempts

        results.append(
            EscalationResponse(
                source_type="AGENT_ACTION",
                source_id=act.agent_action_id,
                event_id=act.event_id,
                department_id=act.department_id,
                department_name=dept_name,
                action_type=act.action_type,
                execution_status=act.execution_status.value if hasattr(act.execution_status, "value") else str(act.execution_status),
                decision_summary=formatted_summary,
                action_timestamp=act.action_timestamp,
                is_resolved=resolved,
                resolved_at=act.resolved_at,
                supervisor_id=act.supervisor_id,
                supervisor_notes=act.supervisor_notes,
                resolution_action=act.resolution_action,
                proof_id=proof_id,
                proof_image_path=proof_image_path,
                proof_employee_id=proof_employee_id,
                work_id=work_id,
                task_name=task_name,
                verification_status=verification_status,
                ai_decision=ai_decision,
                verification_confidence=verification_confidence,
                verification_rationale=verification_rationale,
                verification_attempts=verification_attempts,
                workflow_id=getattr(act, 'workflow_id', None),
            )
        )

    # Source 2: ApprovalRequest rows
    for req in approval_query.all():
        resolved = req.status != "PENDING"

        results.append(
            EscalationResponse(
                source_type="APPROVAL_REQUEST",
                source_id=req.approval_id,
                event_id=None,
                department_id=None,
                department_name="N/A",
                action_type=f"APPROVAL_GATE:{req.sensitive_action}",
                execution_status=req.status,
                decision_summary=req.rationale,
                action_timestamp=req.created_at,
                is_resolved=resolved,
                resolved_at=req.resolved_at,
                supervisor_id=req.supervisor_id,
                supervisor_notes=req.supervisor_notes,
                resolution_action=None,
                context_state_json=req.context_state_json,
            )
        )

    # Sort combined results by timestamp descending
    results.sort(key=lambda r: r.action_timestamp, reverse=True)
    if limit is not None:
        results = results[offset:offset + limit]
    response.headers["X-Escalation-Total-Count"] = str(total_count)
    response.headers["X-Escalation-Pending-Count"] = str(pending_count)
    response.headers["X-Escalation-Resolved-Count"] = str(resolved_count)
    return results


@router.post("/{agent_action_id}/resolve")
def resolve_escalation(
    agent_action_id: int,
    payload: ResolveEscalationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Resolve an AgentActionLog escalation with real domain actions."""

    act = db.query(AgentActionLog).filter(
        AgentActionLog.agent_action_id == agent_action_id
    ).first()
    if not act:
        raise HTTPException(status_code=404, detail="Escalation record not found")

    if act.is_resolved:
        raise HTTPException(status_code=400, detail="Escalation already resolved")

    action = payload.resolution_action
    payload.supervisor_id = current_user.user_id

    if action == "ASSIGN_WORKER" and payload.assigned_employee_id:
        _handle_manual_assignment(act, payload, db)

    elif action == "APPROVE_PROOF":
        _handle_proof_approval(act, payload, db)

    elif action == "REJECT_PROOF":
        _handle_proof_rejection(act, payload, db)

    elif action == "EXTEND_DEADLINE" and (payload.extend_preset or payload.extend_hours):
        _handle_deadline_extension(act, payload, db)

    elif action == "CANCEL_TASK":
        _handle_task_cancellation(act, payload, db)

    elif action == "RUN_ASSIGNMENT_CYCLE":
        _handle_run_assignment_cycle(act, payload, db)

    elif action == "REALLOCATE_ABSENTEE_TASKS":
        _handle_reallocate_absentee_tasks(act, payload, db)

    elif action == "SNOOZE_ABSENTEE":
        _handle_snooze_absentee(act, payload, db)

    else:
        # Generic resolution: mark resolved without domain action
        pass

    # Mark escalation as resolved
    act.is_resolved = True
    act.resolved_at = datetime.now()
    act.supervisor_id = payload.supervisor_id
    act.supervisor_notes = payload.resolution_notes
    act.resolution_action = action
    act.execution_status = AgentActionStatusEnum.SUCCESS

    db.commit()

    # Record supervisor override experience
    try:
        from app.services.workflow_experience_service import record_workflow_experience
        from app.orchestrator.constants import ResolutionType
        record_workflow_experience(
            db=db,
            event_type=act.action_type,
            resolution_type=ResolutionType.SUPERVISOR_OVERRIDE,
            department_id=act.department_id,
            resolution_action=action,
            metadata_extra={"agent_action_id": agent_action_id},
        )
        db.commit()
    except Exception:
        pass

    from app.services.outbox_dispatcher import signal_outbox_wake
    signal_outbox_wake()
    return {"message": "Escalation resolved successfully", "agent_action_id": agent_action_id}


# Domain action handlers

def _handle_manual_assignment(act: AgentActionLog, payload: ResolveEscalationRequest, db: Session):
    """Create TaskAssignment, update work queue, and update worker memory."""
    work_id = _extract_work_id(act, db, payload.work_id)
    if not work_id:
        raise HTTPException(status_code=400, detail="Cannot determine work_id for manual assignment")

    work_item = db.query(DepartmentWorkQueue).filter(
        DepartmentWorkQueue.work_id == work_id
    ).first()
    if not work_item:
        raise HTTPException(status_code=404, detail=f"Work item {work_id} not found")

    if work_item.queue_status not in [WorkQueueStatusEnum.PENDING_ASSIGNED, WorkQueueStatusEnum.ASSIGNED]:
        raise HTTPException(
            status_code=400,
            detail=f"Work item status is {work_item.queue_status.value}, expected PENDING_ASSIGNED or ASSIGNED"
        )

    employee = db.query(Employee).filter(
        Employee.employee_id == payload.assigned_employee_id
    ).first()
    if not employee:
        raise HTTPException(status_code=404, detail=f"Employee {payload.assigned_employee_id} not found")

    # Validate employee belongs to the work item's department
    if employee.department_id != work_item.department_id:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Employee {employee.name} (dept={employee.department_id}) "
                f"is not in the task's department (dept={work_item.department_id})"
            ),
        )

    # Check if an active assignment already exists; if so, preempt it to allow reassignment
    existing = db.query(TaskAssignment).filter(
        TaskAssignment.work_id == work_id,
        TaskAssignment.assignment_status.in_([
            AssignmentStatusEnum.ASSIGNED,
            AssignmentStatusEnum.IN_PROGRESS,
        ]),
    ).first()
    if existing:
        existing.assignment_status = AssignmentStatusEnum.PREEMPTED

    # Create assignment
    assignment = TaskAssignment(
        work_id=work_id,
        employee_id=payload.assigned_employee_id,
        assignment_status=AssignmentStatusEnum.ASSIGNED,
        assigned_at=datetime.now(),
    )
    db.add(assignment)

    # Update work queue status
    work_item.queue_status = WorkQueueStatusEnum.ASSIGNED

    # Reset overdue due_date based on task estimated_time or 60 min fallback
    now_time = datetime.now()
    if work_item.due_date and work_item.due_date < now_time:
        duration_mins = work_item.task.estimated_time if (work_item.task and work_item.task.estimated_time) else 60
        work_item.due_date = now_time + timedelta(minutes=duration_mins)

    # Log event
    event = EventLog(
        event_log="MANUAL_SUPERVISOR_ASSIGNMENT",
        source_module="ESCALATION_RESOLUTION",
        work_id=work_id,
    )
    db.add(event)
    db.flush()

    # Log agent action for audit
    audit = AgentActionLog(
        event_id=event.event_id,
        department_id=work_item.department_id,
        action_type="MANUAL_SUPERVISOR_ASSIGNMENT",
        execution_status=AgentActionStatusEnum.SUCCESS,
        decision_summary=(
            f"Supervisor manually assigned employee {payload.assigned_employee_id} "
            f"(name={employee.name}) to work_id={work_id}"
        ),
        is_resolved=True,
        resolved_at=datetime.now(),
        supervisor_id=payload.supervisor_id,
    )
    db.add(audit)

    # Update worker memory
    memory = db.query(WorkerMemory).filter(
        WorkerMemory.employee_id == payload.assigned_employee_id
    ).first()
    if memory:
        memory.pending_task = (memory.pending_task or 0) + 1

    db.flush()


def _handle_proof_approval(act: AgentActionLog, payload: ResolveEscalationRequest, db: Session):
    """Record the reviewer decision and resume the linked workflow."""
    wf_id = getattr(act, 'workflow_id', None)
    if not wf_id:
        raise HTTPException(status_code=400, detail="Proof resolution requires a valid workflow trace")

    work_id = _extract_work_id(act, db, payload.work_id)
    proof = _get_proof_for_action(act, db, payload.work_id) if work_id else None
    if proof is None:
        raise HTTPException(status_code=404, detail="Task proof not found")
    from app.agents.task_verification_agent import approve_task_proof
    approve_task_proof(
        proof.proof_id,
        db,
        reviewer_user_id=payload.supervisor_id,
    )

    from app.orchestrator.hospital_orchestrator import resume_workflow
    resume_workflow(
        workflow_id=wf_id,
        supervisor_inputs={"proof_verified": True},
        db=db,
    )


def _handle_proof_rejection(act: AgentActionLog, payload: ResolveEscalationRequest, db: Session):
    """Record the reviewer decision and resume the linked workflow."""
    wf_id = getattr(act, 'workflow_id', None)
    if not wf_id:
        raise HTTPException(status_code=400, detail="Proof resolution requires a valid workflow trace")

    work_id = _extract_work_id(act, db, payload.work_id)
    proof = _get_proof_for_action(act, db, payload.work_id) if work_id else None
    if proof is None:
        raise HTTPException(status_code=404, detail="Task proof not found")
    from app.agents.task_verification_agent import reject_task_proof
    reject_task_proof(
        proof.proof_id,
        payload.rejection_reason or "Rejected by supervisor",
        db,
        reviewer_user_id=payload.supervisor_id,
    )

    from app.orchestrator.hospital_orchestrator import resume_workflow
    resume_workflow(
        workflow_id=wf_id,
        supervisor_inputs={
            "proof_verified": False,
            "rejection_reason": payload.rejection_reason,
        },
        db=db,
    )



def _handle_deadline_extension(act: AgentActionLog, payload: ResolveEscalationRequest, db: Session):
    """Extend work item due_date using preset or explicit hours."""
    work_id = _extract_work_id(act, db, payload.work_id)
    if not work_id:
        raise HTTPException(status_code=400, detail="Cannot determine work_id for deadline extension")

    work_item = db.query(DepartmentWorkQueue).filter(
        DepartmentWorkQueue.work_id == work_id
    ).first()
    if not work_item:
        raise HTTPException(status_code=404, detail=f"Work item {work_id} not found")

    base_time = work_item.due_date or datetime.now()

    if payload.extend_preset:
        if payload.extend_preset == "END_OF_DAY":
            # Set to 11:59 PM today (naive local)
            work_item.due_date = base_time.replace(hour=23, minute=59, second=0, microsecond=0)
        elif payload.extend_preset in DEADLINE_PRESETS:
            hours = DEADLINE_PRESETS[payload.extend_preset]
            work_item.due_date = base_time + timedelta(hours=hours)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown extend_preset: {payload.extend_preset}")
    elif payload.extend_hours:
        work_item.due_date = base_time + timedelta(hours=payload.extend_hours)
    else:
        raise HTTPException(status_code=400, detail="No deadline extension value provided")

    db.flush()


def _handle_task_cancellation(act: AgentActionLog, payload: ResolveEscalationRequest, db: Session):
    """Cancel work item using the task management cancellation path."""
    from app.agents.task_management_agent import cancel_work_item

    work_id = _extract_work_id(act, db, payload.work_id)
    if not work_id:
        raise HTTPException(status_code=400, detail="Cannot determine work_id for cancellation")

    cancel_work_item(work_id=work_id, db=db)


# Utility helpers

def _extract_work_id(act: AgentActionLog, db: Session, explicit_work_id: Optional[int] = None) -> Optional[int]:
    """Extract work_id from the linked EventLog, assignment, or summary text."""
    if explicit_work_id is not None:
        return int(explicit_work_id)

    if act.event_id:
        event = db.query(EventLog).filter(EventLog.event_id == act.event_id).first()
        if event:
            if event.work_id:
                return event.work_id
            if event.assignment_id:
                assignment = db.query(TaskAssignment).filter(TaskAssignment.assignment_id == event.assignment_id).first()
                if assignment and assignment.work_id:
                    return assignment.work_id

    summary = act.decision_summary or ""
    for pattern in [
        r'work_id\s*[:=]\s*(\d+)',
        r'work_id=(\d+)',
        r'work\s*[:=]\s*(\d+)',
    ]:
        match = re.search(pattern, summary, re.IGNORECASE)
        if match:
            return int(match.group(1))

    if act.event_id:
        event = db.query(EventLog).filter(EventLog.event_id == act.event_id).first()
        if event and event.employee_id:
            assignment = (
                db.query(TaskAssignment)
                .join(DepartmentWorkQueue, DepartmentWorkQueue.work_id == TaskAssignment.work_id)
                .filter(
                    TaskAssignment.employee_id == event.employee_id,
                    TaskAssignment.assignment_status.in_([
                        AssignmentStatusEnum.ASSIGNED,
                        AssignmentStatusEnum.IN_PROGRESS,
                    ]),
                    DepartmentWorkQueue.department_id == (act.department_id or DepartmentWorkQueue.department_id),
                )
                .order_by(TaskAssignment.assigned_at.desc())
                .first()
            )
            if assignment and assignment.work_id:
                return assignment.work_id

    return None


def _get_proof_for_action(act: AgentActionLog, db: Session, explicit_work_id: Optional[int] = None) -> Optional[TaskProof]:
    """Return the exact proof tied to an escalation, falling back for old rows."""
    match = re.search(r"proof_id=(\d+)", act.decision_summary or "")
    if match:
        proof = db.query(TaskProof).filter(
            TaskProof.proof_id == int(match.group(1))
        ).first()
        if proof:
            return proof

    work_id = _extract_work_id(act, db, explicit_work_id)
    if not work_id:
        return None
    return (
        db.query(TaskProof)
        .filter(TaskProof.work_id == work_id)
        .order_by(TaskProof.submitted_at.desc())
        .first()
    )


def _resolve_department_name(dept_id: Optional[int], summary: Optional[str], db: Session) -> str:
    """Resolve department name from ID or parse from decision_summary."""
    if not dept_id and summary:
        m = re.search(r'dept(?:_id)?=(\d+)', summary, re.IGNORECASE)
        if m:
            dept_id = int(m.group(1))

    if dept_id:
        dept = db.query(Department).filter(Department.department_id == dept_id).first()
        if dept:
            return dept.department_name
    return "N/A"


def _format_summary(summary: str) -> str:
    """Standardise summary format for display."""
    formatted = summary
    if "HUMAN_REVIEW_REQUIRED" in formatted:
        if re.search(r'\(dept=\d+,\s*skill=([^\)]+)\)', formatted, re.IGNORECASE):
            formatted = re.sub(
                r'\(dept=\d+,\s*skill=([^\)]+)\)',
                r'SKILL=\1',
                formatted,
                flags=re.IGNORECASE
            )
        elif "No employee skilled for" in formatted:
            formatted = re.sub(
                r"No employee skilled for ['\"]?(['\".]+)['\"]?\.?",
                r"No available worker has the required skill or prior experience. SKILL=\1",
                formatted,
                flags=re.IGNORECASE
            )
    return formatted


# Absentee and assignment cycle resolution helpers

def _extract_absentee_info(act: AgentActionLog, db: Session) -> dict:
    """Extract employee_id and roster_id from the escalation context.

    Primary path: structural lookups via EventLog.employee_id and
    OrchestratorTrace.input_payload_json.
    Fallback: regex parsing of decision_summary.
    """
    import json
    from app.models.orchestrator_trace import OrchestratorTrace

    info = {"employee_id": None, "roster_id": None}

    # Structural: employee_id from linked EventLog
    if act.event_id:
        event = db.query(EventLog).filter(EventLog.event_id == act.event_id).first()
        if event and event.employee_id:
            info["employee_id"] = event.employee_id

    # Structural: roster_id from OrchestratorTrace input payload
    if act.workflow_id:
        trace = db.query(OrchestratorTrace).filter(
            OrchestratorTrace.workflow_id == act.workflow_id
        ).first()
        if trace and trace.input_payload_json:
            try:
                trace_payload = json.loads(trace.input_payload_json)
                if "roster_id" in trace_payload:
                    info["roster_id"] = int(trace_payload["roster_id"])
            except (json.JSONDecodeError, ValueError):
                pass

    # Fallback: regex on decision_summary
    summary = act.decision_summary or ""
    if not info["employee_id"]:
        m = re.search(r'employee_id=(\d+)', summary)
        if m:
            info["employee_id"] = int(m.group(1))
    if not info["roster_id"]:
        m = re.search(r'roster_id=(\d+)', summary)
        if m:
            info["roster_id"] = int(m.group(1))

    return info


def _assign_selected_pending_tasks(work_ids: list, db: Session) -> dict:
    """Attempt to auto-assign each selected pending task.

    Calls _assign_task per work_id in unlimited mode. Collects per-task
    results so a single failure does not abort the entire resolution.
    """
    from app.agents.assignment_agent import _assign_task

    successes = []
    failures = []

    for w_id in work_ids:
        try:
            result = _assign_task(work_id=w_id, db=db, candidates_override=None)
            if result is not None:
                successes.append({"work_id": w_id, "status": "ASSIGNED"})
            else:
                failures.append({"work_id": w_id, "reason": "No candidate available (capacity full)"})
        except Exception as exc:
            failures.append({"work_id": w_id, "reason": str(exc)})

    return {"successes": successes, "failures": failures}


def _handle_run_assignment_cycle(act: AgentActionLog, payload: ResolveEscalationRequest, db: Session):
    """Trigger the automated assignment cycle for the escalation's department."""
    from app.agents.assignment_agent import run_assignment_cycle

    dept_id = act.department_id
    if not dept_id:
        raise HTTPException(status_code=400, detail="Cannot determine department for assignment cycle")

    run_assignment_cycle(department_id=dept_id, db=db, trigger="ESCALATION_RESOLUTION")


def _handle_reallocate_absentee_tasks(act: AgentActionLog, payload: ResolveEscalationRequest, db: Session):
    """Assign selected pending tasks and trigger a full department assignment cycle."""
    from app.agents.assignment_agent import run_assignment_cycle

    info = _extract_absentee_info(act, db)
    dept_id = act.department_id
    if not dept_id:
        raise HTTPException(status_code=400, detail="Cannot determine department for reallocation")

    # Assign supervisor-selected tasks immediately
    assign_result = {"successes": [], "failures": []}
    if payload.selected_work_ids:
        assign_result = _assign_selected_pending_tasks(payload.selected_work_ids, db)

    # Trigger full department assignment cycle for remaining pending tasks
    run_assignment_cycle(department_id=dept_id, db=db, trigger="ESCALATION_RESOLUTION")

    # Audit log
    event = EventLog(
        event_log="ABSENTEE_TASKS_REALLOCATED",
        source_module="ESCALATION_RESOLUTION",
        employee_id=info.get("employee_id"),
    )
    db.add(event)
    db.flush()


def _handle_snooze_absentee(act: AgentActionLog, payload: ResolveEscalationRequest, db: Session):
    """Snooze the absentee escalation: revert roster to SCHEDULED and wait."""
    from app.models.shift_roster import ShiftRoster
    from app.models.enums import RosterStatusEnum
    from app.services.system_config_service import get_config_value

    info = _extract_absentee_info(act, db)
    roster_id = info.get("roster_id")
    employee_id = info.get("employee_id")

    # Revert roster status from ABSENT back to SCHEDULED
    if roster_id:
        roster = db.query(ShiftRoster).filter(ShiftRoster.roster_id == roster_id).first()
        if roster and roster.roster_status == RosterStatusEnum.ABSENT:
            roster.roster_status = RosterStatusEnum.SCHEDULED

    # Assign supervisor-selected tasks immediately
    if payload.selected_work_ids:
        _assign_selected_pending_tasks(payload.selected_work_ids, db)

    # Read configured snooze duration
    snooze_minutes = get_config_value(db, "ABSENTEE_SNOOZE_MINUTES", 20)

    # Create strict-format snooze audit entry for watcher tracking
    snooze_action = AgentActionLog(
        event_id=act.event_id,
        department_id=act.department_id,
        agent_id=act.agent_id,
        action_type="SNOOZE_ABSENTEE",
        execution_status=AgentActionStatusEnum.SUCCESS,
        decision_summary=f"SNOOZE_ABSENTEE roster_id={roster_id} employee_id={employee_id} snooze_minutes={snooze_minutes}",
        is_resolved=True,
        resolved_at=datetime.now(),
        supervisor_id=payload.supervisor_id,
    )
    db.add(snooze_action)
    db.flush()
