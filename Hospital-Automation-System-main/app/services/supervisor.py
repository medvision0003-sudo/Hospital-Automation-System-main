"""
Supervisor service layer.

Centralizes business logic for creating supervisor task requests,
including resolving due times from offsets and applying default
priorities from the task template.

Each request is written atomically with a SUPERVISOR_REQUEST_CREATED
outbox event so the orchestrator picks it up for processing.
"""

from datetime import datetime, time, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models.enums import DueOffsetEnum, HospitalEventEnum, PriorityEnum
from app.models.supervisor_task_request import SupervisorTaskRequest
from app.models.task_master import TaskMaster
from app.schemas.supervisor_task_request import SupervisorTaskRequestCreate
from app.services.outbox_dispatcher import create_outbox_event, signal_outbox_wake


# Offset to timedelta mapping
_OFFSET_DELTAS = {
    DueOffsetEnum.ONE_HOUR: timedelta(hours=1),
    DueOffsetEnum.TWO_HOURS: timedelta(hours=2),
    DueOffsetEnum.FOUR_HOURS: timedelta(hours=4),
    DueOffsetEnum.END_OF_DAY: None,
}


def _resolve_due_time(
    due_time: Optional[datetime],
    due_offset: Optional[DueOffsetEnum],
) -> datetime:
    """Resolve an absolute due_time from the input fields.

    Priority order:
        1. Explicit due_time (if provided, use it directly).
        2. due_offset relative to server time.
        3. Fallback: end of today (23:59:59).
    """
    if due_time is not None:
        return due_time

    end_of_today = datetime.combine(datetime.now().date(), time(23, 59, 59))

    if due_offset is not None:
        delta = _OFFSET_DELTAS.get(due_offset)
        if delta is not None:
            return datetime.now() + delta
        return end_of_today

    return end_of_today


def _apply_default_priority(
    db: Session,
    task_id: int,
    priority: Optional[PriorityEnum],
) -> PriorityEnum:
    """Resolve the priority to write to the database.

    If the supervisor provided a priority, use it.
    Otherwise, fetch the default from the TaskMaster template.
    Falls back to MEDIUM if the template has no priority set.
    """
    if priority is not None:
        return priority

    task = (
        db.query(TaskMaster)
        .filter(TaskMaster.task_id == task_id)
        .first()
    )
    if task and task.priority_category:
        return task.priority_category

    return PriorityEnum.MEDIUM


def create_supervisor_request(
    db: Session,
    request_data: SupervisorTaskRequestCreate,
) -> SupervisorTaskRequest:
    """Create a single supervisor task request with resolved defaults."""

    resolved_due = _resolve_due_time(request_data.due_time, request_data.due_offset)
    resolved_priority = _apply_default_priority(db, request_data.task_id, request_data.priority)

    record = SupervisorTaskRequest(
        task_id=request_data.task_id,
        supervisor_id=request_data.supervisor_id,
        priority=resolved_priority,
        due_time=resolved_due,
        remarks=request_data.remarks,
    )
    db.add(record)
    db.flush()

    create_outbox_event(
        db=db,
        event_type=HospitalEventEnum.SUPERVISOR_REQUEST_CREATED.value,
        payload={"request_id": record.request_id},
    )
    db.commit()
    db.refresh(record)
    signal_outbox_wake()
    return record


def create_supervisor_requests_bulk(
    db: Session,
    requests_data: list[SupervisorTaskRequestCreate],
) -> dict:
    """Create multiple supervisor task requests in a single atomic transaction.

    Returns a dict with the count of created records and the records themselves.
    Rolls back the entire batch on any error to prevent partial persistence.
    """

    created = []
    try:
        for item in requests_data:
            resolved_due = _resolve_due_time(item.due_time, item.due_offset)
            resolved_priority = _apply_default_priority(db, item.task_id, item.priority)

            record = SupervisorTaskRequest(
                task_id=item.task_id,
                supervisor_id=item.supervisor_id,
                priority=resolved_priority,
                due_time=resolved_due,
                remarks=item.remarks,
            )
            db.add(record)
            created.append(record)

        db.flush()

        for record in created:
            create_outbox_event(
                db=db,
                event_type=HospitalEventEnum.SUPERVISOR_REQUEST_CREATED.value,
                payload={"request_id": record.request_id},
            )

        db.commit()

        for record in created:
            db.refresh(record)

    except Exception:
        db.rollback()
        raise

    signal_outbox_wake()
    return {
        "created": len(created),
        "requests": created,
    }


# Overtime duration to timedelta mapping
_OVERTIME_DELTAS = {
    "ONE_HOUR": timedelta(hours=1),
    "TWO_HOURS": timedelta(hours=2),
    "FOUR_HOURS": timedelta(hours=4),
}


def resolve_shift_handover_choice_a(
    approval_id: int,
    overtime_duration: str,
    db: Session,
) -> dict:
    """Grant overtime extension for a shift handover review.

    Sets the roster to OVERTIME status with a calculated end time.
    Worker retains all ASSIGNED and IN_PROGRESS tasks.
    """
    import json
    from app.models.approval_request import ApprovalRequest
    from app.models.shift_roster import ShiftRoster
    from app.models.shift import Shift
    from app.models.enums import RosterStatusEnum

    approval = db.query(ApprovalRequest).filter(
        ApprovalRequest.approval_id == approval_id
    ).first()
    if not approval:
        raise ValueError(f"ApprovalRequest {approval_id} not found")

    if approval.status != "PENDING":
        raise ValueError(f"ApprovalRequest {approval_id} is already {approval.status}")

    context = json.loads(approval.context_state_json) if approval.context_state_json else {}
    roster_id = context.get("roster_id")

    roster = db.query(ShiftRoster).filter(ShiftRoster.roster_id == roster_id).first()
    if not roster:
        raise ValueError(f"ShiftRoster {roster_id} not found")

    # Calculate overtime end time from original shift end
    shift_obj = db.query(Shift).filter(Shift.shift_id == roster.shift_id).first()
    if shift_obj:
        shift_end_dt = datetime.combine(roster.work_date, shift_obj.end_time)
        shift_start_dt = datetime.combine(roster.work_date, shift_obj.start_time)
        if shift_end_dt <= shift_start_dt:
            shift_end_dt += timedelta(days=1)
    else:
        shift_end_dt = datetime.now()

    delta = _OVERTIME_DELTAS.get(overtime_duration, timedelta(hours=1))
    overtime_end = shift_end_dt + delta

    # Map duration string to hours integer
    duration_hours_map = {"ONE_HOUR": 1, "TWO_HOURS": 2, "FOUR_HOURS": 4}

    # Update roster to OVERTIME
    roster.roster_status = RosterStatusEnum.OVERTIME
    roster.is_overtime = True
    roster.overtime_duration_hours = duration_hours_map.get(overtime_duration, 1)
    roster.overtime_end_time = overtime_end

    # Mark approval as APPROVED
    approval.status = "APPROVED"
    approval.resolved_at = datetime.now()

    db.flush()

    print(
        f"[SUPERVISOR] Choice A: roster_id={roster_id} -> OVERTIME "
        f"until {overtime_end}, duration={overtime_duration}"
    )

    return {
        "approval_id": approval_id,
        "roster_id": roster_id,
        "choice": "CHOICE_A",
        "overtime_end_time": str(overtime_end),
        "overtime_duration": overtime_duration,
    }


def resolve_shift_handover_choice_b(
    approval_id: int,
    db: Session,
) -> dict:
    """Preempt ASSIGNED tasks and carry forward to incoming shift.

    Only ASSIGNED tasks are preempted. IN_PROGRESS tasks remain with the worker.
    After preemption, roster is completed and reassignment cycle is triggered.
    """
    import json
    from app.models.approval_request import ApprovalRequest
    from app.models.shift_roster import ShiftRoster
    from app.models.task_assignment import TaskAssignment
    from app.models.department_work_queue import DepartmentWorkQueue
    from app.models.worker_memory import WorkerMemory
    from app.models.enums import (
        RosterStatusEnum,
        AssignmentStatusEnum,
        WorkQueueStatusEnum,
    )

    approval = db.query(ApprovalRequest).filter(
        ApprovalRequest.approval_id == approval_id
    ).first()
    if not approval:
        raise ValueError(f"ApprovalRequest {approval_id} not found")

    if approval.status != "PENDING":
        raise ValueError(f"ApprovalRequest {approval_id} is already {approval.status}")

    context = json.loads(approval.context_state_json) if approval.context_state_json else {}
    roster_id = context.get("roster_id")
    employee_id = context.get("employee_id")
    assigned_work_ids = context.get("assigned_work_ids", [])
    department_id = context.get("department_id")

    # Preempt only ASSIGNED tasks (not IN_PROGRESS)
    preempted_count = 0
    for work_id in assigned_work_ids:
        assignment = (
            db.query(TaskAssignment)
            .filter(
                TaskAssignment.work_id == work_id,
                TaskAssignment.employee_id == employee_id,
                TaskAssignment.assignment_status == AssignmentStatusEnum.ASSIGNED,
            )
            .first()
        )
        if assignment:
            assignment.assignment_status = AssignmentStatusEnum.PREEMPTED
            preempted_count += 1

            # Revert work queue item
            work_item = db.query(DepartmentWorkQueue).filter(
                DepartmentWorkQueue.work_id == work_id
            ).first()
            if work_item and work_item.queue_status == WorkQueueStatusEnum.ASSIGNED:
                work_item.queue_status = WorkQueueStatusEnum.PENDING_ASSIGNED

    # Complete the roster
    roster = db.query(ShiftRoster).filter(ShiftRoster.roster_id == roster_id).first()
    if roster:
        roster.roster_status = RosterStatusEnum.COMPLETED

    # Recalculate pending_task for the worker
    if employee_id:
        memory = db.query(WorkerMemory).filter(
            WorkerMemory.employee_id == employee_id
        ).first()
        if memory:
            new_pending = (
                db.query(TaskAssignment)
                .filter(
                    TaskAssignment.employee_id == employee_id,
                    TaskAssignment.assignment_status.in_([
                        AssignmentStatusEnum.ASSIGNED,
                        AssignmentStatusEnum.IN_PROGRESS,
                    ]),
                )
                .count()
            )
            memory.pending_task = new_pending

    # Mark approval as RESOLVED
    approval.status = "RESOLVED"
    approval.resolved_at = datetime.now()

    db.flush()

    print(
        f"[SUPERVISOR] Choice B: preempted {preempted_count} ASSIGNED task(s) "
        f"for roster_id={roster_id}, roster -> COMPLETED"
    )

    # Trigger reassignment cycle for released tasks
    if department_id and preempted_count > 0:
        try:
            from app.agents.assignment_agent import run_assignment_cycle
            run_assignment_cycle(department_id, db)
        except Exception as exc:
            print(f"[SUPERVISOR] Reassignment cycle after Choice B failed: {exc}")

    return {
        "approval_id": approval_id,
        "roster_id": roster_id,
        "choice": "CHOICE_B",
        "preempted_count": preempted_count,
        "assigned_work_ids": assigned_work_ids,
    }
