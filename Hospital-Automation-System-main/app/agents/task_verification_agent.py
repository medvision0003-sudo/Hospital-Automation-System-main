"""Gemini-backed task proof analysis with a fail-safe supervisor review path."""

import time
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Optional

from sqlalchemy.orm import Session

from app.models.department_work_queue import DepartmentWorkQueue
from app.models.task_proof import TaskProof
from app.models.agent_action_log import AgentActionLog
from app.models.agent_table import AgentTable
from app.models.event_log import EventLog
from app.models.enums import (
    TaskProofStatusEnum,
    AgentActionStatusEnum,
    WorkQueueStatusEnum,
)
from app.orchestrator.execution import AgentExecutionError
from app.orchestrator.constants import ExecutionStatus


def _resolve_agent_id(db: Session) -> int:
    """Look up TASK_VERIFICATION_AGENT ID from agent_table, fallback to 7."""
    agent = (
        db.query(AgentTable)
        .filter(AgentTable.agent_name == "TASK_VERIFICATION_AGENT")
        .first()
    )
    return agent.agent_id if agent else 7


def _get_task_name_for_work(work_item: DepartmentWorkQueue) -> Optional[str]:
    """Extract the task name from the work item's related TaskMaster."""
    if work_item.task and work_item.task.task_name:
        return work_item.task.task_name.upper()
    return None


def verify_task_proof(
    work_id: int,
    proof_image_path: str,
    db: Session,
    workflow_id: str = None,
) -> dict:
    """Evaluate submitted image evidence and route uncertain results to review."""

    agent_id = _resolve_agent_id(db)
    started = time.perf_counter()

    work_item = (
        db.query(DepartmentWorkQueue)
        .filter(DepartmentWorkQueue.work_id == work_id)
        .first()
    )
    if not work_item:
        raise AgentExecutionError(
            "TASK_VERIFICATION_AGENT",
            f"Work item {work_id} not found.",
        )

    if work_item.queue_status != WorkQueueStatusEnum.ASSIGNED:
        raise AgentExecutionError(
            "TASK_VERIFICATION_AGENT",
            f"Work item {work_id} is not ASSIGNED (current: {work_item.queue_status.value}).",
        )

    latest_proof = (
        db.query(TaskProof)
        .filter(
            TaskProof.work_id == work_id,
            TaskProof.proof_image_path == proof_image_path,
        )
        .order_by(TaskProof.submitted_at.desc())
        .first()
    )
    if not latest_proof:
        raise AgentExecutionError(
            "TASK_VERIFICATION_AGENT",
            f"No proof record found for work_id {work_id}.",
        )

    task_name = _get_task_name_for_work(work_item) or "UNKNOWN"
    from app.services.gemini_proof_verifier import (
        VerificationUnavailable,
        analyze_task_proof,
    )
    from app.services.system_config_service import get_config_value

    image_path = PurePosixPath(proof_image_path)
    if (
        "\\" in proof_image_path
        or ".." in image_path.parts
        or not proof_image_path.startswith("uploads/")
    ):
        raise AgentExecutionError(
            "TASK_VERIFICATION_AGENT",
            "Proof image path is not a valid internal upload path.",
        )
    upload_root = Path("uploads").resolve()
    resolved_image = (upload_root / Path(*image_path.parts[1:])).resolve()
    if upload_root not in resolved_image.parents or not resolved_image.is_file():
        raise AgentExecutionError(
            "TASK_VERIFICATION_AGENT",
            "Proof image is missing or outside the uploads directory.",
        )

    threshold = float(
        get_config_value(db, "MIN_VERIFICATION_CONFIDENCE_SCORE", 0.70)
    )
    automated_approval_enabled = bool(
        get_config_value(db, "ENABLE_AUTOMATED_PROOF_APPROVAL", False)
    )
    try:
        result = analyze_task_proof(
            resolved_image,
            task_name,
            work_item.task.description if work_item.task else None,
        )
        verification_provider = result.get("provider", "GEMINI")
    except VerificationUnavailable as exc:
        decision = "NEEDS_REVIEW"
        confidence = None
        rationale = str(exc)
        verification_provider = "UNAVAILABLE"
    else:
        decision = result["decision"]
        confidence = result["confidence"]
        rationale = result["reason"]
    auto_approval = automated_approval_enabled or verification_provider == "DEMO"
    if confidence is not None and confidence < threshold:
        decision = "NEEDS_REVIEW"
        rationale = (
            f"{rationale} Confidence {confidence:.2f} is below the "
            f"configured threshold {threshold:.2f}."
        )

    latest_proof.ai_decision = decision
    latest_proof.verification_confidence = confidence
    latest_proof.verification_rationale = rationale
    review_required = decision == "NEEDS_REVIEW" or (
        decision == "VERIFIED" and not auto_approval
    )
    if review_required:
        latest_proof.verification_status = TaskProofStatusEnum.PENDING
    elif decision == "REJECTED":
        latest_proof.verification_status = TaskProofStatusEnum.REJECTED
    else:
        latest_proof.verification_status = TaskProofStatusEnum.PENDING

    action = None
    if review_required:
        event = EventLog(
            event_log="PROOF_REVIEW_REQUIRED",
            source_module="TASK_VERIFICATION_AGENT",
            work_id=work_id,
        )
        db.add(event)
        db.flush()
        action = AgentActionLog(
            event_id=event.event_id,
            department_id=work_item.department_id,
            agent_id=agent_id,
            action_type="PROOF_REVIEW_REQUIRED",
            action_timestamp=datetime.now(),
            execution_status=AgentActionStatusEnum.PENDING,
            decision_summary=(
                f"HUMAN_REVIEW_REQUIRED: work_id={work_id}, proof_id={latest_proof.proof_id}, "
                f"AI decision={decision}, confidence={confidence}. {rationale}"
            ),
            is_resolved=False,
            workflow_id=workflow_id,
            execution_time_ms=int((time.perf_counter() - started) * 1000),
        )
        db.add(action)
        db.flush()
    else:
        action = AgentActionLog(
            event_id=None,
            department_id=work_item.department_id,
            agent_id=agent_id,
            action_type="VERIFY_TASK_PROOF",
            action_timestamp=datetime.now(),
            execution_status=AgentActionStatusEnum.SUCCESS,
            decision_summary=(
                f"work_id={work_id}, proof_id={latest_proof.proof_id}, "
                f"AI decision={decision}, confidence={confidence}. {rationale}"
            ),
            workflow_id=workflow_id,
            execution_time_ms=int((time.perf_counter() - started) * 1000),
        )
        db.add(action)
        db.flush()

    db.flush()
    return {
        "review_required": review_required,
        "work_id": work_id,
        "proof_id": latest_proof.proof_id,
        "proof_verified": decision == "VERIFIED" and not review_required,
        "decision": decision,
        "verification_confidence": confidence,
        "verification_rationale": rationale,
        "verification_provider": verification_provider,
        "agent_action_id": action.agent_action_id,
        "workflow": [
            {"agent": "TASK_VERIFICATION_AGENT", "status": ExecutionStatus.SUCCESS},
        ],
    }


def approve_task_proof(
    proof_id: int,
    db: Session,
    reviewer_user_id: Optional[int] = None,
) -> TaskProof:
    """Mark a proof as VERIFIED by supervisor."""
    proof = db.query(TaskProof).filter(TaskProof.proof_id == proof_id).first()
    if not proof:
        raise AgentExecutionError(
            "TASK_VERIFICATION_AGENT",
            f"Proof {proof_id} not found.",
        )
    proof.verification_status = TaskProofStatusEnum.VERIFIED
    if proof.ai_decision is None:
        proof.ai_decision = "NEEDS_REVIEW"
    proof.verification_rationale = proof.verification_rationale or "Approved by supervisor"
    proof.verified_at = datetime.now()
    proof.reviewer_user_id = reviewer_user_id
    db.flush()

    # Find the assigned employee to notify them
    from app.models.task_assignment import TaskAssignment
    from app.models.enums import AssignmentStatusEnum

    assignment = (
        db.query(TaskAssignment)
        .filter(
            TaskAssignment.work_id == proof.work_id,
            TaskAssignment.assignment_status == AssignmentStatusEnum.ASSIGNED,
        )
        .order_by(TaskAssignment.assigned_at.desc())
        .first()
    )
    if not assignment:
        # Fallback to any latest assignment for this work item
        assignment = (
            db.query(TaskAssignment)
            .filter(TaskAssignment.work_id == proof.work_id)
            .order_by(TaskAssignment.assigned_at.desc())
            .first()
        )

    if assignment and assignment.employee_id:
        # Queue WhatsApp approval notification via outbox (caller owns commit)
        from app.services.outbox_dispatcher import create_outbox_event
        from app.models.enums import HospitalEventEnum
        create_outbox_event(
            db=db,
            event_type=HospitalEventEnum.SEND_WHATSAPP_NOTIFICATION.value,
            payload={
                "employee_id": assignment.employee_id,
                "work_id": proof.work_id,
                "notification_type": "PROOF_APPROVED",
            },
            dedupe_key=f"SEND_WHATSAPP_PROOF_APPROVED:proof_id={proof.proof_id}",
        )

    return proof


def reject_task_proof(
    proof_id: int,
    reason: str,
    db: Session,
    reviewer_user_id: Optional[int] = None,
) -> TaskProof:
    """Mark a proof as REJECTED by supervisor."""
    proof = db.query(TaskProof).filter(TaskProof.proof_id == proof_id).first()
    if not proof:
        raise AgentExecutionError(
            "TASK_VERIFICATION_AGENT",
            f"Proof {proof_id} not found.",
        )
    proof.verification_status = TaskProofStatusEnum.REJECTED
    if proof.ai_decision is None:
        proof.ai_decision = "NEEDS_REVIEW"
    if reviewer_user_id is None:
        proof.verification_rationale = (
            f"Rejected by automated verification: "
            f"{reason or 'insufficient evidence'}"
        )
    elif reason and reason != "Rejected by supervisor":
        proof.verification_rationale = f"Rejected by supervisor: {reason}"
    else:
        proof.verification_rationale = "Rejected by supervisor"
    proof.verified_at = datetime.now()
    proof.reviewer_user_id = reviewer_user_id
    db.flush()

    # Find the assigned employee to notify them
    from app.models.task_assignment import TaskAssignment
    from app.models.enums import AssignmentStatusEnum

    assignment = (
        db.query(TaskAssignment)
        .filter(
            TaskAssignment.work_id == proof.work_id,
            TaskAssignment.assignment_status == AssignmentStatusEnum.ASSIGNED,
        )
        .order_by(TaskAssignment.assigned_at.desc())
        .first()
    )
    if not assignment:
        # Fallback to any latest assignment for this work item
        assignment = (
            db.query(TaskAssignment)
            .filter(TaskAssignment.work_id == proof.work_id)
            .order_by(TaskAssignment.assigned_at.desc())
            .first()
        )

    if assignment and assignment.employee_id:
        # Queue WhatsApp rejection notification via outbox (caller owns commit)
        from app.services.outbox_dispatcher import create_outbox_event
        from app.models.enums import HospitalEventEnum
        create_outbox_event(
            db=db,
            event_type=HospitalEventEnum.SEND_WHATSAPP_NOTIFICATION.value,
            payload={
                "employee_id": assignment.employee_id,
                "work_id": proof.work_id,
                "notification_type": "PROOF_REJECTED",
                "reason": reason,
            },
            dedupe_key=f"SEND_WHATSAPP_PROOF_REJECTED:proof_id={proof.proof_id}",
        )

    return proof
