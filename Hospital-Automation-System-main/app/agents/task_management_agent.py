from datetime import datetime, time
from typing import Optional

from sqlalchemy.orm import Session

from app.models.task_master import TaskMaster
from app.models.department_work_queue import DepartmentWorkQueue
from app.models.task_assignment import TaskAssignment
from app.models.event_log import EventLog
from app.models.agent_action_log import AgentActionLog
from app.models.enums import (
    WorkQueueStatusEnum,
    AssignmentStatusEnum,
    PriorityEnum,
    AgentActionStatusEnum,
    TaskStatusEnum,
)
from app.orchestrator.execution import AgentExecutionError
from app.orchestrator.constants import TASK_MANAGEMENT_AGENT, ExecutionStatus


def create_work_item(
    task_id: int,
    due_date: datetime,
    db: Session,
    priority_override: Optional[str] = None,
    commit: bool = True,
    shift_id: Optional[int] = None,
    workflow_id: Optional[str] = None,
) -> dict:
    # Convert string or timezone-aware due_date to naive local datetime
    if isinstance(due_date, str):
        due_date = datetime.fromisoformat(due_date.replace("Z", "+00:00").replace("z", "+00:00"))
    if due_date is not None and due_date.tzinfo is not None:
        due_date = due_date.astimezone().replace(tzinfo=None)

    """
    Rule-based work-item creation agent.
    Steps:
        1. Validate the task exists in TaskMaster and is ACTIVE.
        2. Derive department_id and priority from the task record.
        3. Check for duplicate active work items (warn but allow).
        4. Create a DepartmentWorkQueue row with PENDING_ASSIGNED.
        5. Write an EventLog row for the TASK_CREATED event.
        6. Write an AgentActionLog row recording the decision.

    Returns a dict summarising what was created, or raises ValueError on failure.
    """

    # Step 1: validate task exists and is active
    task = (
        db.query(TaskMaster)
        .filter(TaskMaster.task_id == task_id)
        .first()
    )
    if task is None:
        raise AgentExecutionError(
            TASK_MANAGEMENT_AGENT,
            f"Task {task_id} not found in TaskMaster.",
        )

    if task.task_state != TaskStatusEnum.ACTIVE:
        raise AgentExecutionError(
            TASK_MANAGEMENT_AGENT,
            f"Task {task_id} is not active "
            f"(current task_state: {task.task_state.value}).",
        )

    # Step 2: derive department and priority from TaskMaster
    department_id = task.department_id
    department_name = task.department.department_name if task.department else str(department_id)

    if priority_override is not None:
        try:
            priority_enum = PriorityEnum(priority_override.upper())
        except ValueError:
            raise AgentExecutionError(
                TASK_MANAGEMENT_AGENT,
                f"Invalid priority_override '{priority_override}'. "
                f"Must be one of: {[p.value for p in PriorityEnum]}",
            )
        priority_source = "override"
    else:
        priority_enum = task.priority_category
        priority_source = "TaskMaster"

    # Step 3: check for duplicate active work items (warn but allow)
    active_statuses = [
        WorkQueueStatusEnum.PENDING_ASSIGNED,
        WorkQueueStatusEnum.ASSIGNED,
    ]
    existing_active = (
        db.query(DepartmentWorkQueue)
        .filter(
            DepartmentWorkQueue.task_id == task_id,
            DepartmentWorkQueue.department_id == department_id,
            DepartmentWorkQueue.queue_status.in_(active_statuses),
        )
        .count()
    )
    if existing_active > 0:
        print(
            f"[TASK_MANAGEMENT_AGENT] Warning: {existing_active} active "
            f"work item(s) already exist for task {task_id} in "
            f"department {department_id}. Creating another instance."
        )

    # Step 4: create DepartmentWorkQueue entry
    work_item = DepartmentWorkQueue(
        task_id=task_id,
        department_id=department_id,
        shift_id=shift_id,
        priority=priority_enum,
        queue_status=WorkQueueStatusEnum.PENDING_ASSIGNED,
        due_date=due_date,
    )
    db.add(work_item)
    db.flush()

    print(
        f"[TASK_MANAGEMENT_AGENT] Created work_id {work_item.work_id} "
        f"for task '{task.task_name}' in department '{department_name}' "
        f"(priority: {priority_enum.value} from {priority_source})."
    )

    # Step 5: create EventLog entry
    event = EventLog(
        event_log="TASK_CREATED",
        source_module="TASK_MANAGEMENT_AGENT",
        work_id=work_item.work_id,
    )
    db.add(event)
    db.flush()

    # Step 6: create AgentActionLog entry
    action = AgentActionLog(
        event_id=event.event_id,
        department_id=department_id,
        agent_id=3,
        action_type="CREATE_WORK_ITEM",
        execution_status=AgentActionStatusEnum.SUCCESS,
        workflow_id=workflow_id,
        decision_summary=(
            f"Created work_id {work_item.work_id} for task_id {task_id} "
            f"('{task.task_name}') in department {department_id} "
            f"('{department_name}') with priority {priority_enum.value} "
            f"(source: {priority_source})."
        ),
    )
    db.add(action)
    db.flush()

    if commit:
        db.commit()

    print(
        f"[TASK_MANAGEMENT_AGENT] Done. "
        f"work_id={work_item.work_id}, "
        f"event_id={event.event_id}, "
        f"agent_action_id={action.agent_action_id}"
    )

    return {
        "work_id": work_item.work_id,
        "event_id": event.event_id,
        "agent_action_id": action.agent_action_id,
        "task_name": task.task_name,
        "department_id": department_id,
        "shift_id": shift_id,
        "department_name": department_name,
        "priority": priority_enum.value,
        "priority_source": priority_source,
        "workflow": [
            {"agent": TASK_MANAGEMENT_AGENT, "status": ExecutionStatus.SUCCESS},
        ],
    }


def generate_recurring_work(db: Session) -> list[dict]:
    """
    Start-of-day scheduling agent.

    Reads all active TaskSchedule entries (joined with ACTIVE TaskMaster records)
    and creates today's work queue entries for each one.

    Steps:
        1. Query TaskSchedule joined with TaskMaster where
           TaskMaster.task_state=ACTIVE and TaskSchedule.is_active=True.
        2. For each schedule, call create_work_item with a due_date of end-of-day
           (23:59:59). Department and priority are derived automatically.
        3. Return a list of created work item summaries.
    """
    from app.models.task_schedule import TaskSchedule

    active_schedules = (
        db.query(TaskSchedule)
        .join(TaskMaster, TaskSchedule.task_id == TaskMaster.task_id)
        .filter(
            TaskMaster.task_state == TaskStatusEnum.ACTIVE,
            TaskSchedule.is_active == True,
        )
        .all()
    )

    if not active_schedules:
        print("[TASK_MANAGEMENT_AGENT] No active schedules found.")
        return []

    print(
        f"[TASK_MANAGEMENT_AGENT] Found {len(active_schedules)} "
        f"active schedule(s). Creating today's work queue entries."
    )

    end_of_day = datetime.combine(datetime.now().date(), time(23, 59, 59))
    results = []

    for schedule in active_schedules:
        try:
            result = create_work_item(
                task_id=schedule.task_id,
                due_date=end_of_day,
                db=db,
            )
            results.append(result)
        except ValueError as exc:
            print(
                f"[TASK_MANAGEMENT_AGENT] Skipping schedule {schedule.schedule_id} "
                f"('{schedule.schedule_name}'): {exc}"
            )

    print(
        f"[TASK_MANAGEMENT_AGENT] Start-of-day complete. "
        f"Created {len(results)} work queue item(s)."
    )

    return results


# Valid event types and their target statuses
_STATUS_MAP = {
    "TASK_ASSIGNED":  (WorkQueueStatusEnum.ASSIGNED,   AssignmentStatusEnum.ASSIGNED,    "ASSIGN_TASK"),
    "TASK_COMPLETED": (WorkQueueStatusEnum.COMPLETED,  AssignmentStatusEnum.COMPLETED,   "COMPLETE_WORK"),
    "TASK_CANCELLED": (WorkQueueStatusEnum.CANCELLED,  AssignmentStatusEnum.CANCELLED,   "CANCEL_WORK"),
}


def update_work_status(
    work_id: int,
    event_type: str,
    db: Session,
    employee_id: Optional[int] = None,
    commit: bool = True,
) -> dict:
    """
    Transitions a DepartmentWorkQueue item and its related TaskAssignment
    through lifecycle states based on event_type.
        TASK_ASSIGNED  - marks queue ASSIGNED
        TASK_COMPLETED - marks queue COMPLETED, assignment COMPLETED + completed_at
        TASK_CANCELLED - marks queue CANCELLED, assignment CANCELLED
    Returns a dict summarising the update, or raises ValueError on failure.
    """

    # Validate event_type
    if event_type not in _STATUS_MAP:
        raise ValueError(
            f"Unknown event_type '{event_type}'. "
            f"Must be one of: {list(_STATUS_MAP.keys())}"
        )

    queue_status, assignment_status, action_type = _STATUS_MAP[event_type]

    # Step 1: load and validate the work item
    work_item = (
        db.query(DepartmentWorkQueue)
        .filter(DepartmentWorkQueue.work_id == work_id)
        .first()
    )
    if work_item is None:
        raise ValueError(f"Work queue item {work_id} not found.")

    old_status = work_item.queue_status

    # Step 2: update DepartmentWorkQueue status
    work_item.queue_status = queue_status

    # Step 3: update related TaskAssignment (if any active assignment exists)
    assignment_id = None
    resolved_employee_id = employee_id

    if event_type in ("TASK_COMPLETED", "TASK_CANCELLED"):
        active_assignment = (
            db.query(TaskAssignment)
            .filter(
                TaskAssignment.work_id == work_id,
                TaskAssignment.assignment_status.in_([
                    AssignmentStatusEnum.ASSIGNED,
                    AssignmentStatusEnum.IN_PROGRESS,
                ]),
            )
            .first()
        )
        if active_assignment:
            active_assignment.assignment_status = assignment_status
            if event_type == "TASK_COMPLETED":
                active_assignment.completed_at = datetime.now()
            assignment_id = active_assignment.assignment_id
            resolved_employee_id = active_assignment.employee_id

    # Step 4: create EventLog
    event = EventLog(
        event_log=event_type,
        source_module="TASK_MANAGEMENT_AGENT",
        work_id=work_id,
        employee_id=resolved_employee_id,
        assignment_id=assignment_id,
    )
    db.add(event)
    db.flush()

    # Step 5: create AgentActionLog
    action = AgentActionLog(
        event_id=event.event_id,
        department_id=work_item.department_id,
        agent_id=3,
        action_type=action_type,
        execution_status=AgentActionStatusEnum.SUCCESS,
        decision_summary=(
            f"Updated work_id {work_id} from {old_status.value} to "
            f"{queue_status.value} via {event_type}."
        ),
    )
    db.add(action)

    # Callers like complete_work_item pass commit=False
    # so status + worker-memory land in one transaction
    if commit:
        db.commit()
    else:
        db.flush()

    print(
        f"[TASK_MANAGEMENT_AGENT] {event_type}: work_id {work_id} "
        f"{old_status.value} -> {queue_status.value}"
    )

    return {
        "work_id": work_id,
        "old_status": old_status.value,
        "new_status": queue_status.value,
        "event_type": event_type,
        "event_id": event.event_id,
        "agent_action_id": action.agent_action_id,
        "assignment_id": assignment_id,
        "employee_id": resolved_employee_id,
    }


def complete_work_item(
    work_id: int,
    db: Session,
    proof_verified: Optional[bool] = None,
    rejection_reason: Optional[str] = None,
) -> dict:
    """Mark work item COMPLETED. Single commit.

    If proof_verified is False, the proof is rejected and the function
    raises GracefulWorkflowAbort without completing the task. The work
    item remains in ASSIGNED status for worker resubmission.
    """
    if proof_verified is False:
        from app.models.task_proof import TaskProof
        from app.models.enums import TaskProofStatusEnum
        from app.orchestrator.execution import GracefulWorkflowAbort

        proof = (
            db.query(TaskProof)
            .filter(TaskProof.work_id == work_id)
            .order_by(TaskProof.submitted_at.desc())
            .first()
        )
        if not proof:
            raise AgentExecutionError(
                TASK_MANAGEMENT_AGENT,
                f"Proof for work_id {work_id} not found.",
            )

        if proof.verification_status != TaskProofStatusEnum.REJECTED:
            from app.agents.task_verification_agent import reject_task_proof
            reject_task_proof(
                proof_id=proof.proof_id,
                reason=rejection_reason or "Rejected by supervisor",
                db=db,
            )

        db.commit()
        from app.services.outbox_dispatcher import signal_outbox_wake
        signal_outbox_wake()

        raise GracefulWorkflowAbort(
            status="PROOF_REJECTED",
            message="Task completion proof was rejected by supervisor",
        )

    if proof_verified is not True:
        from app.models.department_work_queue import DepartmentWorkQueue
        from app.models.task_master import TaskMaster
        from app.models.task_proof import TaskProof
        from app.models.enums import TaskProofStatusEnum

        work_item = (
            db.query(DepartmentWorkQueue)
            .filter(DepartmentWorkQueue.work_id == work_id)
            .first()
        )
        task = db.query(TaskMaster).filter(
            TaskMaster.task_id == work_item.task_id
        ).first() if work_item else None
        if task and task.requires_proof:
            verified_proof = (
                db.query(TaskProof)
                .filter(
                    TaskProof.work_id == work_id,
                    TaskProof.verification_status == TaskProofStatusEnum.VERIFIED,
                )
                .first()
            )
            if not verified_proof:
                raise AgentExecutionError(
                    TASK_MANAGEMENT_AGENT,
                    f"Work item {work_id} requires verified proof before completion.",
                )

    # If proof_verified is True, delegate approval to TaskVerificationAgent if not already verified
    if proof_verified is True:
        from app.models.task_proof import TaskProof
        from app.models.enums import TaskProofStatusEnum
        proof = (
            db.query(TaskProof)
            .filter(TaskProof.work_id == work_id)
            .order_by(TaskProof.submitted_at.desc())
            .first()
        )
        if not proof:
            raise AgentExecutionError(
                TASK_MANAGEMENT_AGENT,
                f"Proof for work_id {work_id} not found.",
            )

        if proof.verification_status != TaskProofStatusEnum.VERIFIED:
            from app.agents.task_verification_agent import approve_task_proof
            approve_task_proof(proof_id=proof.proof_id, db=db)

    result = update_work_status(work_id, "TASK_COMPLETED", db, commit=False)

    db.commit()
    from app.services.outbox_dispatcher import signal_outbox_wake
    signal_outbox_wake()

    result["workflow"] = [
        {"agent": TASK_MANAGEMENT_AGENT, "status": ExecutionStatus.SUCCESS},
    ]
    return result


def cancel_work_item(
    work_id: int,
    db: Session,
) -> dict:
    """Mark work item CANCELLED. Single commit."""
    result = update_work_status(work_id, "TASK_CANCELLED", db, commit=False)
    db.commit()
    result["workflow"] = [
        {"agent": TASK_MANAGEMENT_AGENT, "status": ExecutionStatus.SUCCESS},
    ]
    return result


def carry_forward_pending_tasks(db: Session) -> list[dict]:
    """
    Carry-forward scheduler. Finds overdue PENDING_ASSIGNED items
    and extends their deadline to end-of-today.
    """
    now = datetime.now()
    end_of_day = datetime.combine(now.date(), time(23, 59, 59))

    overdue = (
        db.query(DepartmentWorkQueue)
        .filter(
            DepartmentWorkQueue.queue_status.in_([
                WorkQueueStatusEnum.PENDING_ASSIGNED,
                WorkQueueStatusEnum.ASSIGNED,
            ]),
            DepartmentWorkQueue.due_date < now,
        )
        .all()
    )

    if not overdue:
        print("[TASK_MANAGEMENT_AGENT] No overdue pending tasks to carry forward.")
        return []

    print(
        f"[TASK_MANAGEMENT_AGENT] Found {len(overdue)} overdue pending task(s). "
        f"Carrying forward to {end_of_day}."
    )

    results = []
    for item in overdue:
        old_due = item.due_date
        item.due_date = end_of_day

        event = EventLog(
            event_log="TASK_CARRIED_FORWARD",
            source_module="TASK_MANAGEMENT_AGENT",
            work_id=item.work_id,
        )
        db.add(event)
        db.flush()

        action = AgentActionLog(
            event_id=event.event_id,
            department_id=item.department_id,
            agent_id=3,
            action_type="CARRY_FORWARD",
            execution_status=AgentActionStatusEnum.SUCCESS,
            decision_summary=(
                f"Carried forward work_id {item.work_id} "
                f"from {old_due} to {end_of_day}."
            ),
        )
        db.add(action)

        results.append({
            "work_id": item.work_id,
            "old_due_date": str(old_due),
            "new_due_date": str(end_of_day),
            "event_id": event.event_id,
        })

    db.commit()
    print(f"[TASK_MANAGEMENT_AGENT] Carried forward {len(results)} task(s).")
    return results
