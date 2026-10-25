"""
Agent Adapters

Thin wrappers around existing agent functions. Each adapter
translates the standardised (payload, context) calling convention
into the specific arguments each agent function expects.

Rules:
  - Adapters contain NO business logic.
  - Adapters only unpack payload/context and call the real function.
  - Existing agents continue to own DB logic, audit logging, etc.
"""

from app.agents.task_management_agent import (
    create_work_item,
    complete_work_item,
    cancel_work_item,
)
from app.agents.assignment_agent import (
    _assign_task,
    automate_work_item_assignment,
    run_assignment_cycle,
    assign_emergency_work_items,
)
from app.agents.workforce_agent import (
    _get_today_roster,
    checkin_worker,
    checkout_worker,
    handle_shift_end,
    mark_worker_absent,
)
from app.services.recurring_task_scheduler import generate_scheduled_tasks
from app.agents.emergency_response_agent import handle_emergency
from app.models.agent_action_log import AgentActionLog
from app.models.enums import EmergencyTypeEnum
from app.models.supervisor_task_request import SupervisorTaskRequest
from app.orchestrator.constants import AssignmentTrigger, ExecutionStatus
from app.orchestrator.execution import AgentExecutionError, GracefulWorkflowAbort


def _normalize_event_type(event_type) -> str:
    """Extract a plain string from event_type (handles str and Enum)."""
    if isinstance(event_type, str):
        return event_type
    return getattr(event_type, "value", str(event_type))


def _link_action_to_workflow(context, action_id):
    if action_id is None:
        return
    context.db.query(AgentActionLog).filter(
        AgentActionLog.agent_action_id == action_id,
    ).update(
        {"workflow_id": context.workflow_id},
        synchronize_session="fetch",
    )


def create_work_item_adapter(payload: dict, context) -> dict:
    """Wrap task_management_agent.create_work_item."""
    due_date = payload.get("due_date")
    if not due_date:
        from datetime import datetime, timedelta
        from app.models.task_master import TaskMaster
        task = context.db.query(TaskMaster).filter(TaskMaster.task_id == payload["task_id"]).first()
        est_minutes = task.estimated_time if (task and task.estimated_time) else 60
        due_date = datetime.now() + timedelta(minutes=est_minutes)

    return create_work_item(
        task_id=payload["task_id"],
        due_date=due_date,
        db=context.db,
        priority_override=payload.get("priority_override"),
        shift_id=payload.get("shift_id"),
        workflow_id=context.workflow_id,
    )


def assign_work_item_adapter(payload: dict, context) -> dict:
    """Wrap assignment_agent._assign_task for a single work item.

    Passes through the is_emergency flag from the event payload so that
    urgent dynamic task requests can trigger the preemption path inside
    the assignment agent.
    """
    return _assign_task(
        work_id=payload["work_id"],
        db=context.db,
        is_emergency=payload.get("is_emergency", False),
        workflow_id=context.workflow_id,
    )


def checkin_worker_adapter(payload: dict, context) -> dict:
    """Wrap workforce_agent.checkin_worker."""
    result = checkin_worker(
        employee_id=payload["employee_id"],
        db=context.db,
        device_id=payload.get("device_id"),
        current_time=payload.get("occurred_at"),
        trigger_source=payload.get("trigger_source"),
    )
    _link_action_to_workflow(context, result.get("agent_action_id"))
    return result


def checkout_worker_adapter(payload: dict, context) -> dict:
    """Wrap workforce_agent.checkout_worker for orchestrated sign-out."""
    result = checkout_worker(
        employee_id=payload["employee_id"],
        db=context.db,
        current_time=payload.get("occurred_at"),
        trigger_source=payload.get("trigger_source"),
        incomplete_task_action=payload.get("incomplete_task_action", "REASSIGN"),
    )
    _link_action_to_workflow(context, result.get("agent_action_id"))
    return result


def run_assignment_cycle_adapter(payload: dict, context) -> dict:
    """Wrap assignment_agent.run_assignment_cycle.

    When the orchestrator event is WORKER_CHECKED_IN the trigger is
    forced to WORKER_CHECKIN so the assignment agent applies fair-share
    allocation. shift_id is passed through from the payload if present
    (it may be None when the employee has no roster entry for today).

    Sets context.status from the cycle result so the orchestrator trace
    reflects escalation states (PARTIAL_SUCCESS, FAILED).
    """
    event_name = _normalize_event_type(context.event_type)

    if event_name == "WORKER_CHECKED_IN":
        trigger = AssignmentTrigger.WORKER_CHECKIN
    else:
        trigger = payload.get("trigger")

    result = run_assignment_cycle(
        department_id=payload["department_id"],
        db=context.db,
        trigger=trigger,
        shift_id=payload.get("shift_id"),
        workflow_id=context.workflow_id,
        current_time=payload.get("occurred_at"),
    )

    # Propagate cycle status to orchestrator context
    cycle_status = result.get("status")
    if cycle_status and context.status != ExecutionStatus.PARTIAL_SUCCESS:
        context.status = cycle_status

    return result


def generate_shift_tasks_adapter(payload: dict, context) -> dict:
    """Create this shift's task-library work when a qualified worker checks in."""
    if payload.get("shift_id") is None:
        return {"generated_work_ids": [], "generated_count": 0, "tasks": []}

    result = generate_scheduled_tasks(
        context.db,
        department_id=payload["department_id"],
        shift_id=payload["shift_id"],
        current_time=payload.get("occurred_at"),
        dispatch_events=False,
        include_future=True,
        workflow_id=context.workflow_id,
    )
    if result["failures"]:
        context.status = ExecutionStatus.PARTIAL_SUCCESS
    return {
        **result,
        "generated_work_ids": [task["work_id"] for task in result["tasks"]],
    }


def run_assignment_cycle_for_shift_start_adapter(payload: dict, context) -> dict:
    """Reevaluate work when an employee's scheduled shift becomes active."""
    from app.models.shift_roster import ShiftRoster

    roster = (
        context.db.query(ShiftRoster)
        .filter(ShiftRoster.roster_id == payload["roster_id"])
        .first()
    )
    if roster is None or roster.employee is None:
        raise ValueError(f"Roster {payload['roster_id']} has no employee.")

    department_id = roster.employee.department_id
    if department_id is None:
        return {
            "status": "SUCCESS",
            "department_id": None,
            "total_assigned": 0,
            "total_failed": 0,
            "assigned": [],
            "failures": [],
        }

    result = run_assignment_cycle(
        department_id=department_id,
        db=context.db,
        trigger="SHIFT_STARTED",
        shift_id=roster.shift_id,
        workflow_id=context.workflow_id,
    )
    if result.get("status"):
        context.status = result["status"]
    return result


def handle_emergency_adapter(payload: dict, context) -> dict:
    """Wrap emergency_response_agent.handle_emergency.

    Normalises the agent's 'failures' key to 'task_creation_failures'
    and ensures it is always present as a list (even when empty).
    """
    result = handle_emergency(
        emergency_type=EmergencyTypeEnum(payload["emergency_type"]),
        location=payload["location"],
        reported_by=payload["reported_by"],
        payload=payload,
        db=context.db,
    )

    # Normalise: agent returns "failures", capability declares "task_creation_failures"
    result["task_creation_failures"] = result.pop("failures", [])
    return result


def assign_emergency_work_items_adapter(payload: dict, context) -> dict:
    """Delegate to assignment_agent.assign_emergency_work_items.

    The domain function handles resilient per-item assignment and
    triggers rerouting for any preempted tasks internally.
    """
    from app.orchestrator.constants import ExecutionStatus

    work_ids = payload.get("work_ids", [])
    task_creation_failures = payload.get("task_creation_failures", [])

    result = assign_emergency_work_items(
        work_ids=work_ids,
        db=context.db,
    )

    # Determine final status
    if not work_ids:
        context.status = ExecutionStatus.FAILED
    elif task_creation_failures or result.get("assignment_failures"):
        context.status = ExecutionStatus.PARTIAL_SUCCESS
    else:
        context.status = ExecutionStatus.SUCCESS

    return result


def complete_work_item_adapter(payload: dict, context) -> dict:
    """Wrap task_management_agent.complete_work_item."""
    return complete_work_item(
        work_id=payload["work_id"],
        db=context.db,
        proof_verified=payload.get("proof_verified"),
        rejection_reason=payload.get("rejection_reason"),
    )


def cancel_work_item_adapter(payload: dict, context) -> dict:
    """Wrap task_management_agent.cancel_work_item."""
    return cancel_work_item(
        work_id=payload["work_id"],
        db=context.db,
    )


def update_worker_task_metrics_adapter(payload: dict, context) -> dict:
    """Wrap workforce_agent.update_worker_task_metrics."""
    from app.agents.workforce_agent import update_worker_task_metrics
    return update_worker_task_metrics(
        employee_id=payload.get("employee_id"),
        new_status=payload.get("new_status"),
        db=context.db,
    )


def load_supervisor_request_adapter(payload: dict, context) -> dict:
    """Load a SupervisorTaskRequest and check idempotency.

    If the request has already been processed, raises GracefulWorkflowAbort
    so the executor halts without marking a failure.
    """
    request_id = payload["request_id"]

    request = (
        context.db.query(SupervisorTaskRequest)
        .filter(SupervisorTaskRequest.request_id == request_id)
        .first()
    )
    if not request:
        raise ValueError(f"SupervisorTaskRequest {request_id} not found.")

    if request.processed_at is not None:
        print(f"[ADAPTER] Request {request_id} already processed. Aborting gracefully.")
        raise GracefulWorkflowAbort(
            status="ALREADY_PROCESSED",
            message=f"SupervisorTaskRequest {request_id} already processed",
            metadata={"request_id": request_id},
        )

    return {
        "task_id": request.task_id,
        "due_date": request.due_time,
        "priority_override": request.priority.value if request.priority else None,
        "request_id": request_id,
    }


def mark_supervisor_request_processed_adapter(payload: dict, context) -> dict:
    """Mark a SupervisorTaskRequest as processed after successful assignment."""
    from datetime import datetime

    request_id = payload["request_id"]

    request = (
        context.db.query(SupervisorTaskRequest)
        .filter(SupervisorTaskRequest.request_id == request_id)
        .first()
    )
    if not request:
        raise ValueError(f"SupervisorTaskRequest {request_id} not found.")

    request.processed_at = datetime.now()
    context.db.commit()

    print(f"[ADAPTER] SupervisorTaskRequest {request_id} marked as processed.")
    return {"request_id": request_id}


# Step 3 Autonomous Event Adapters


def _record_automatic_assignment_outcome(
    *,
    db,
    event,
    work_id: int,
    department_id: int | None,
    workflow_id: str | None,
    result: dict,
    outcome_name: str,
) -> dict:
    """Record an automatic assignment result and retain human review as fallback."""
    from datetime import datetime
    from app.models.enums import AgentActionStatusEnum

    assigned = result.get("assigned", [])
    if assigned:
        assignees = ", ".join(
            f"{entry['employee_name']} (employee_id={entry['employee_id']})"
            for entry in assigned
        )
        action = AgentActionLog(
            event_id=event.event_id,
            department_id=department_id,
            agent_id=2,
            action_type="AUTOMATIC_REASSIGNMENT",
            execution_status=AgentActionStatusEnum.SUCCESS,
            decision_summary=(
                f"{outcome_name}: work_id={work_id} automatically assigned to "
                f"{assignees} using department, shift, skill, and workload eligibility."
            ),
            is_resolved=True,
            resolved_at=datetime.now(),
            resolution_action="AUTO_ASSIGNED",
            workflow_id=workflow_id,
        )
        db.add(action)
        db.flush()
        return {
            "work_id": work_id,
            "action": "AUTO_ASSIGNED",
            "agent_action_id": action.agent_action_id,
            "assigned": assigned,
        }

    action_type = result.get("action")
    reason = result.get("reason")
    failures = result.get("failures", [])
    if not reason and failures:
        reason = failures[0].get("reason")
    if action_type == "ALREADY_PROCESSED":
        return {
            "work_id": work_id,
            "action": action_type,
            "agent_action_id": result.get("agent_action_id"),
        }
    if action_type in ("ALREADY_ASSIGNED", "NO_PENDING_WORK"):
        action = AgentActionLog(
            event_id=event.event_id,
            department_id=department_id,
            agent_id=2,
            action_type="AUTOMATIC_ASSIGNMENT",
            execution_status=AgentActionStatusEnum.SUCCESS,
            decision_summary=f"{outcome_name}: work_id={work_id} required no reassignment.",
            is_resolved=True,
            resolved_at=datetime.now(),
            resolution_action="NO_CHANGE_REQUIRED",
            workflow_id=workflow_id,
        )
        db.add(action)
        db.flush()
        return {
            "work_id": work_id,
            "action": "NO_CHANGE_REQUIRED",
            "agent_action_id": action.agent_action_id,
        }

    summary = (
        f"{outcome_name}: work_id={work_id} remains pending automatic assignment. "
        f"{reason or 'No eligible checked-in worker matched the required shift and skills.'} "
        "Supervisor review is required until a qualified worker becomes available."
    )
    escalation = None
    if workflow_id:
        escalation = (
            db.query(AgentActionLog)
            .filter(
                AgentActionLog.workflow_id == workflow_id,
                AgentActionLog.action_type == "ESCALATION",
                AgentActionLog.decision_summary.contains(f"work_id={work_id}"),
            )
            .order_by(AgentActionLog.agent_action_id.desc())
            .first()
        )
    if escalation is not None:
        escalation.event_id = event.event_id
        escalation.decision_summary = summary
        escalation.is_resolved = False
        escalation.resolved_at = None
        action_id = escalation.agent_action_id
    else:
        escalation = AgentActionLog(
            event_id=event.event_id,
            department_id=department_id,
            agent_id=2,
            action_type="ESCALATION",
            execution_status=AgentActionStatusEnum.PENDING,
            decision_summary=summary,
            is_resolved=False,
            workflow_id=workflow_id,
        )
        db.add(escalation)
        db.flush()
        action_id = escalation.agent_action_id

    return {
        "work_id": work_id,
        "action": "HUMAN_REVIEW_REQUIRED",
        "agent_action_id": action_id,
        "reason": reason,
    }


def handle_task_timeout_adapter(payload: dict, context) -> dict:
    """Automatically reroute overdue unstarted work before requesting review."""
    from app.models.department_work_queue import DepartmentWorkQueue
    from app.models.event_log import EventLog

    work_id = payload["work_id"]
    db = context.db

    work_item = db.query(DepartmentWorkQueue).filter(DepartmentWorkQueue.work_id == work_id).first()
    if work_item is None:
        raise ValueError(f"Work queue item {work_id} not found.")

    event = EventLog(
        event_log="TASK_TIMEOUT_DETECTED",
        source_module="TASK_TIMEOUT_WATCHER",
        work_id=work_id,
    )
    db.add(event)
    db.flush()

    result = automate_work_item_assignment(
        work_id=work_id,
        db=db,
        workflow_id=context.workflow_id,
        trigger="TASK_TIMEOUT",
        reassign_unstarted=True,
    )
    outcome = _record_automatic_assignment_outcome(
        db=db,
        event=event,
        work_id=work_id,
        department_id=work_item.department_id,
        workflow_id=context.workflow_id,
        result=result,
        outcome_name="TASK_TIMEOUT_PREEMPTION",
    )
    if result.get("status"):
        context.status = result["status"]
    return outcome


def handle_staff_shortage_adapter(payload: dict, context) -> dict:
    """Automatically retry pending work before escalating a staffing shortage."""
    from app.models.department_work_queue import DepartmentWorkQueue
    from app.models.event_log import EventLog

    work_id = payload["work_id"]
    db = context.db

    work_item = db.query(DepartmentWorkQueue).filter(DepartmentWorkQueue.work_id == work_id).first()
    if work_item is None:
        raise ValueError(f"Work queue item {work_id} not found.")

    event = EventLog(
        event_log="STAFF_SHORTAGE_DETECTED",
        source_module="STAFF_SHORTAGE_WATCHER",
        work_id=work_id,
    )
    db.add(event)
    db.flush()

    result = automate_work_item_assignment(
        work_id=work_id,
        db=db,
        workflow_id=context.workflow_id,
        trigger="STAFF_SHORTAGE",
    )
    outcome = _record_automatic_assignment_outcome(
        db=db,
        event=event,
        work_id=work_id,
        department_id=work_item.department_id,
        workflow_id=context.workflow_id,
        result=result,
        outcome_name="STAFF_SHORTAGE",
    )
    if result.get("status"):
        context.status = result["status"]
    return outcome


def rebalance_overloaded_worker_adapter(payload: dict, context) -> dict:
    """Wrap assignment_agent.rebalance_overloaded_worker."""
    from app.agents.assignment_agent import rebalance_overloaded_worker
    return rebalance_overloaded_worker(
        employee_id=payload["employee_id"],
        db=context.db,
    )


def handle_shift_change_adapter(payload: dict, context) -> dict:
    """Wrap workforce_agent.handle_shift_end for shift-end cleanup.

    Cancels active assignments, reverts work items to PENDING_ASSIGNED,
    and recalculates pending_task metrics for the worker.
    """
    return handle_shift_end(
        roster_id=payload["roster_id"],
        db=context.db,
    )


def handle_staff_absent_adapter(payload: dict, context) -> dict:
    """Mark a roster entry absent and record the detection without escalating it."""
    from datetime import datetime
    from app.models.shift_roster import ShiftRoster
    from app.models.event_log import EventLog
    from app.models.agent_action_log import AgentActionLog
    from app.models.enums import AgentActionStatusEnum

    result = mark_worker_absent(
        roster_id=payload["roster_id"],
        db=context.db,
    )

    roster_id = payload["roster_id"]
    db = context.db

    roster = db.query(ShiftRoster).filter(ShiftRoster.roster_id == roster_id).first()
    dept_id = roster.employee.department_id if (roster and roster.employee) else None
    emp_id = roster.employee_id if roster else None

    event = EventLog(
        event_log="STAFF_ABSENT_DETECTED",
        source_module="ABSENTEE_WATCHER",
        employee_id=emp_id,
    )
    db.add(event)
    db.flush()

    action = AgentActionLog(
        event_id=event.event_id,
        department_id=dept_id,
        agent_id=1,
        action_type="STAFF_ABSENCE_HANDLED",
        execution_status=AgentActionStatusEnum.SUCCESS,
        decision_summary=(
            f"STAFF_ABSENCE_DETECTED: Worker (employee_id={emp_id}, "
            f"roster_id={roster_id}) marked ABSENT; unstarted tasks queued "
            "for automatic reassignment."
        ),
        is_resolved=True,
        resolved_at=datetime.now(),
        resolution_action="AUTO_REASSIGNMENT_STARTED",
        workflow_id=context.workflow_id,
    )
    db.add(action)
    db.flush()

    result["agent_action_id"] = action.agent_action_id
    return result


def reassign_absent_worker_tasks_adapter(payload: dict, context) -> dict:
    """Reassign released, unstarted work after an employee is marked absent."""
    from app.models.shift_roster import ShiftRoster

    roster = (
        context.db.query(ShiftRoster)
        .filter(ShiftRoster.roster_id == payload["roster_id"])
        .first()
    )
    if roster is None or roster.employee is None or roster.employee.department_id is None:
        return {"total_assigned": 0, "total_failed": 0, "assigned": [], "failures": []}

    released_work_ids = payload.get("released_work_ids", [])
    if not released_work_ids:
        return {
            "status": ExecutionStatus.SUCCESS,
            "total_assigned": 0,
            "total_failed": 0,
            "assigned": [],
            "failures": [],
        }

    result = run_assignment_cycle(
        department_id=roster.employee.department_id,
        db=context.db,
        trigger="STAFF_ABSENT",
        shift_id=roster.shift_id,
        work_ids=released_work_ids,
        workflow_id=context.workflow_id,
    )
    if result.get("status"):
        context.status = result["status"]
    return result


def verify_task_proof_adapter(payload: dict, context) -> dict:
    """Delegate proof verification to the LangGraph sub-flow, then halt if review is needed.

    The LangGraph graph coordinates the inspection and routing decision.
    When supervisor review is required (default), the adapter raises
    GracefulWorkflowAbort so complete_work_item_for_proof does not
    auto-execute.
    """
    from app.orchestrator.graphs.langgraph_adapter import run_langgraph_proof_verification
    from app.orchestrator.execution import GracefulWorkflowAbort

    result = run_langgraph_proof_verification(
        db=context.db,
        work_id=payload["work_id"],
        proof_image_path=payload["proof_image_path"],
        workflow_id=context.workflow_id,
    )

    if result.get("review_required"):
        raise GracefulWorkflowAbort(
            status="PENDING_HUMAN_APPROVAL",
            message=f"Task proof for work_id={payload['work_id']} requires supervisor review",
            metadata=result,
        )

    return result


def send_whatsapp_task_notification_adapter(payload: dict, context) -> dict:
    """Wrap communication_agent.send_whatsapp_task_notification for outbox-driven dispatch."""
    from app.agents.communication_agent import send_whatsapp_task_notification

    return send_whatsapp_task_notification(
        db=context.db,
        employee_id=payload["employee_id"],
        work_id=payload["work_id"],
        notification_type=payload.get("notification_type", "ASSIGNMENT"),
        reason=payload.get("reason"),
        workflow_id=context.workflow_id,
    )


# Domain-state idempotency check callbacks
# Each returns {already_done: True, outputs: {...}, reason: str} to skip,
# or None to let the handler run normally.

def create_work_item_idempotency(payload: dict, context) -> dict | None:
    """Skip if a stable request_id already produced a work item.

    Only fires for SUPERVISOR_REQUEST_CREATED events where request_id
    is a stable external identifier. For plain DYNAMIC_TASK_REQUEST
    (no stable key), returns None so the step executes normally.
    """
    request_id = payload.get("request_id")
    if not request_id:
        return None

    request = (
        context.db.query(SupervisorTaskRequest)
        .filter(SupervisorTaskRequest.request_id == request_id)
        .first()
    )
    if not request or request.processed_at is None:
        return None

    from app.models.department_work_queue import DepartmentWorkQueue
    work_item = (
        context.db.query(DepartmentWorkQueue)
        .filter(DepartmentWorkQueue.task_id == request.task_id)
        .order_by(DepartmentWorkQueue.work_id.desc())
        .first()
    )
    if not work_item:
        return None

    return {
        "already_done": True,
        "outputs": {
            "work_id": work_item.work_id,
            "task_name": work_item.task.task_name if work_item.task else None,
            "department_id": work_item.department_id,
            "department_name": (
                work_item.task.department.department_name
                if work_item.task and work_item.task.department else None
            ),
            "priority": work_item.priority.value if work_item.priority else None,
        },
        "reason": f"SupervisorTaskRequest {request_id} already processed",
    }


def assign_work_item_idempotency(payload: dict, context) -> dict | None:
    """Skip if the work item is terminal or already has an active assignment."""
    from app.models.department_work_queue import DepartmentWorkQueue
    from app.models.task_assignment import TaskAssignment
    from app.models.enums import WorkQueueStatusEnum, AssignmentStatusEnum

    work_id = payload.get("work_id")
    if not work_id:
        return None

    work_item = (
        context.db.query(DepartmentWorkQueue)
        .filter(DepartmentWorkQueue.work_id == work_id)
        .first()
    )
    if not work_item:
        return None

    # If work item is already terminal, skip and return latest assignment if available
    if work_item.queue_status in (
        WorkQueueStatusEnum.COMPLETED,
        WorkQueueStatusEnum.CANCELLED,
    ):
        latest = (
            context.db.query(TaskAssignment)
            .filter(TaskAssignment.work_id == work_id)
            .order_by(TaskAssignment.assignment_id.desc())
            .first()
        )
        outputs = {
            "assignment_id": latest.assignment_id if latest else None,
            "employee_id": latest.employee_id if latest else None,
            "employee_name": (
                latest.employee.name
                if latest and latest.employee else None
            ),
        }
        return {
            "already_done": True,
            "outputs": outputs,
            "reason": f"Work item {work_id} already {work_item.queue_status.value}",
        }

    # Check for an active (non-terminal) assignment
    active = (
        context.db.query(TaskAssignment)
        .filter(
            TaskAssignment.work_id == work_id,
            TaskAssignment.assignment_status.in_([
                AssignmentStatusEnum.ASSIGNED,
                AssignmentStatusEnum.IN_PROGRESS,
            ]),
        )
        .first()
    )
    if active:
        return {
            "already_done": True,
            "outputs": {
                "assignment_id": active.assignment_id,
                "employee_id": active.employee_id,
                "employee_name": (
                    active.employee.name
                    if active.employee else None
                ),
            },
            "reason": f"Work item {work_id} already assigned (assignment {active.assignment_id})",
        }

    return None


def checkin_worker_idempotency(payload: dict, context) -> dict | None:
    """Skip duplicate check-ins while preserving context for reassignment."""
    from app.models.worker_checkin import WorkerCheckin
    from app.models.enums import CheckinStatusEnum

    employee_id = payload.get("employee_id")
    if not employee_id:
        return None

    existing = (
        context.db.query(WorkerCheckin)
        .filter(
            WorkerCheckin.employee_id == employee_id,
            WorkerCheckin.status == CheckinStatusEnum.CHECKED_IN,
        )
        .order_by(WorkerCheckin.checkin_time.desc())
        .first()
    )
    if existing:
        employee = existing.employee
        roster = _get_today_roster(context.db, employee_id)
        return {
            "already_done": True,
            "outputs": {
                "employee_id": employee_id,
                "employee_name": employee.name if employee else None,
                "department_id": employee.department_id if employee else None,
                "department_name": (
                    employee.department.department_name
                    if employee and employee.department
                    else None
                ),
                "shift_id": roster.shift_id if roster else None,
                "roster_id": roster.roster_id if roster else None,
                "checked_in": True,
            },
            "reason": f"Employee {employee_id} already has an active check-in",
        }

    return None


def complete_work_item_idempotency(payload: dict, context) -> dict | None:
    """Skip if the work item is already COMPLETED."""
    from app.models.department_work_queue import DepartmentWorkQueue
    from app.models.task_assignment import TaskAssignment
    from app.models.enums import WorkQueueStatusEnum

    work_id = payload.get("work_id")
    if not work_id:
        return None

    work_item = (
        context.db.query(DepartmentWorkQueue)
        .filter(DepartmentWorkQueue.work_id == work_id)
        .first()
    )
    if not work_item or work_item.queue_status != WorkQueueStatusEnum.COMPLETED:
        return None

    latest = (
        context.db.query(TaskAssignment)
        .filter(TaskAssignment.work_id == work_id)
        .order_by(TaskAssignment.assignment_id.desc())
        .first()
    )
    return {
        "already_done": True,
        "outputs": {
            "work_id": work_id,
            "old_status": "COMPLETED",
            "new_status": "COMPLETED",
            "employee_id": latest.employee_id if latest else None,
        },
        "reason": f"Work item {work_id} already COMPLETED",
    }


def cancel_work_item_idempotency(payload: dict, context) -> dict | None:
    """Skip if the work item is already CANCELLED."""
    from app.models.department_work_queue import DepartmentWorkQueue
    from app.models.task_assignment import TaskAssignment
    from app.models.enums import WorkQueueStatusEnum

    work_id = payload.get("work_id")
    if not work_id:
        return None

    work_item = (
        context.db.query(DepartmentWorkQueue)
        .filter(DepartmentWorkQueue.work_id == work_id)
        .first()
    )
    if not work_item or work_item.queue_status != WorkQueueStatusEnum.CANCELLED:
        return None

    latest = (
        context.db.query(TaskAssignment)
        .filter(TaskAssignment.work_id == work_id)
        .order_by(TaskAssignment.assignment_id.desc())
        .first()
    )
    return {
        "already_done": True,
        "outputs": {
            "work_id": work_id,
            "old_status": "CANCELLED",
            "new_status": "CANCELLED",
            "employee_id": latest.employee_id if latest else None,
        },
        "reason": f"Work item {work_id} already CANCELLED",
    }


def mark_supervisor_request_processed_idempotency(payload: dict, context) -> dict | None:
    """Skip if the supervisor request is already processed."""
    request_id = payload.get("request_id")
    if not request_id:
        return None

    request = (
        context.db.query(SupervisorTaskRequest)
        .filter(SupervisorTaskRequest.request_id == request_id)
        .first()
    )
    if not request or request.processed_at is None:
        return None

    return {
        "already_done": True,
        "outputs": {"request_id": request_id},
        "reason": f"SupervisorTaskRequest {request_id} already marked processed",
    }


def recover_assignment_cycle_adapter(payload: dict, context) -> dict:
    """Delegate to assignment_agent.run_assignment_cycle with explicit recovery trigger.

    Uses AssignmentTrigger.RECOVERY so the cycle runs in unlimited mode
    (not WORKER_CHECKIN fair-share) and the trigger is traceable.
    """
    result = run_assignment_cycle(
        department_id=payload["department_id"],
        db=context.db,
        trigger=AssignmentTrigger.RECOVERY,
        shift_id=payload.get("shift_id"),
    )

    cycle_status = result.get("status")
    if cycle_status:
        context.status = cycle_status

    return result
