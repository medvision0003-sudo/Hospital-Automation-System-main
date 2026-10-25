"""
Event Agent — Gateway Layer

Validates incoming hospital events and forwards them to the
Hospital Orchestrator. Does NOT write EventLog or perform any
business logic. Each downstream agent owns its own logging.

"""

import sys
import argparse
import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.department import Department
from app.models.employee import Employee
from app.models.shift import Shift
from app.models.task_master import TaskMaster
from app.models.supervisor_task_request import SupervisorTaskRequest
from app.models.department_work_queue import DepartmentWorkQueue
from app.models.task_assignment import TaskAssignment
from app.models.shift_roster import ShiftRoster
from app.models.agent_action_log import AgentActionLog
from app.models.orchestrator_trace import OrchestratorTrace
from app.models.enums import AgentActionStatusEnum, HospitalEventEnum
from app.orchestrator.hospital_orchestrator import handle_event
from app.orchestrator.constants import EVENT_AGENT, ExecutionStatus


# Event Rules
# Each event type maps to the payload fields it REQUIRES.
# Validation is generic -- no if/elif chains.

EVENT_RULES = {
    HospitalEventEnum.DYNAMIC_TASK_REQUEST: ["task_id", "due_date"],
    HospitalEventEnum.TASK_COMPLETED:       ["work_id"],
    HospitalEventEnum.TASK_CANCELLED:       ["work_id"],
    HospitalEventEnum.WORKER_CHECKED_IN:    ["employee_id"],
    HospitalEventEnum.WORKER_CHECKED_OUT:   ["employee_id"],
    HospitalEventEnum.SHIFT_STARTED:        ["roster_id"],
    HospitalEventEnum.SUPERVISOR_REQUEST_CREATED: ["request_id"],
    HospitalEventEnum.EMERGENCY_RESPONSE: ["emergency_type", "location", "reported_by"],

    # Autonomous watcher events (Step 3 - Outbox)
    HospitalEventEnum.TASK_TIMEOUT_DETECTED:    ["work_id"],
    HospitalEventEnum.STAFF_SHORTAGE_DETECTED:  ["work_id"],
    HospitalEventEnum.WORKER_OVERLOAD_DETECTED: ["employee_id"],
    HospitalEventEnum.SHIFT_CHANGE_DETECTED:    ["roster_id"],
    HospitalEventEnum.STAFF_ABSENT_DETECTED:    ["roster_id"],

    # Step 4 - Task Proof Verification
    HospitalEventEnum.TASK_PROOF_SUBMITTED: ["work_id", "proof_image_path"],

    # Scheduler event (Task Management Agent)
    HospitalEventEnum.RECURRING_TASK_GENERATED: ["work_id"],

    # WhatsApp notification (Communication Agent)
    HospitalEventEnum.SEND_WHATSAPP_NOTIFICATION: ["employee_id", "work_id"],
}


# DB Reference Validators
# Maps payload field names to the model + column used for existence checks.

DB_VALIDATORS = {
    "employee_id":   (Employee, Employee.employee_id),
    "work_id":       (DepartmentWorkQueue, DepartmentWorkQueue.work_id),
    "assignment_id": (TaskAssignment, TaskAssignment.assignment_id),
    "task_id":       (TaskMaster, TaskMaster.task_id),
    "request_id":    (SupervisorTaskRequest, SupervisorTaskRequest.request_id),
    "roster_id":     (ShiftRoster, ShiftRoster.roster_id),
}


# Internal Helpers

def _log_validation_failure(db: Session, decision_summary: str):
    """Log a FAILED agent action for audit trail on validation errors."""
    action = AgentActionLog(
        event_id=None,
        agent_id=5,
        action_type="VALIDATE_EVENT",
        action_timestamp=datetime.now(),
        execution_status=AgentActionStatusEnum.FAILED,
        decision_summary=decision_summary,
    )
    db.add(action)
    db.commit()
    return action


# Public Function

def publish_event(
    event_type: HospitalEventEnum,
    payload: dict,
    db: Session,
) -> dict:
    """
    Validate a hospital event and forward it to the orchestrator.

    This is the ONLY public function of the Event Agent.
    Everything goes through here.

    Args:
        event_type:    HospitalEventEnum member identifying the event.
        payload:       Dict of event-specific data (varies by event type).
        db:            SQLAlchemy session, forwarded to orchestrator as-is.

    Returns:
        The workflow summary dict from the Hospital Orchestrator.
    """

    print(f"[EVENT_AGENT] Received: {event_type.value}")

    # Step 1: Validate event_type
    if event_type not in EVENT_RULES:
        valid_types = ", ".join(e.value for e in EVENT_RULES)
        error_msg = f"Unknown event_type '{event_type.value}'. Valid types: {valid_types}"
        print(f"[EVENT_AGENT] FAIL: {error_msg}")
        _log_validation_failure(db, error_msg)
        raise ValueError(error_msg)

    # Step 2: Validate required payload fields
    required_fields = EVENT_RULES[event_type]
    missing = [f for f in required_fields if f not in payload or payload[f] is None]

    if missing:
        error_msg = (
            f"{event_type.value} requires {', '.join(missing)} "
            f"but {'it was' if len(missing) == 1 else 'they were'} not provided"
        )
        print(f"[EVENT_AGENT] FAIL: {error_msg}")
        _log_validation_failure(db, error_msg)
        raise ValueError(error_msg)

    # Step 3: Validate database references
    for field_name in required_fields:
        if field_name not in DB_VALIDATORS:
            continue  #  skip fields without DB validators (e.g. due_date)
        model, column = DB_VALIDATORS[field_name]
        value = payload[field_name]
        exists = db.query(column).filter(column == value).first()

        if not exists:
            error_msg = f"{field_name}={value} does not exist in '{model.__tablename__}'"
            print(f"[EVENT_AGENT] FAIL: {error_msg}")
            _log_validation_failure(db, error_msg)
            raise ValueError(error_msg)

    print("[EVENT_AGENT] Validation passed. Forwarding to orchestrator.")

    # Step 4: Forward to Hospital Orchestrator
    result = handle_event(
        event_type=event_type,
        payload=payload,
        db=db,
    )

    # Step 5: Prepend EVENT_AGENT to the execution trace
    if "workflow_execution" in result:
        result["workflow_execution"].insert(0, {
            "agent": EVENT_AGENT,
            "status": ExecutionStatus.SUCCESS,
        })
        workflow_id = result.get("workflow_id")
        if workflow_id:
            trace = db.query(OrchestratorTrace).filter(
                OrchestratorTrace.workflow_id == workflow_id
            ).first()
            if trace:
                trace.workflow_execution_json = json.dumps(
                    result["workflow_execution"],
                    default=str,
                )
                if trace.final_result_json:
                    final_result = json.loads(trace.final_result_json)
                    final_result["workflow_execution"] = result["workflow_execution"]
                    trace.final_result_json = json.dumps(final_result, default=str)
                db.commit()

    print(f"[EVENT_AGENT] Orchestrator returned: status={result.get('status')}")
    return result


# Run directly from terminal

if __name__ == "__main__":
    from app.database.connection import SessionLocal

    parser = argparse.ArgumentParser(
        description="Event Agent -- Validate and forward hospital events.",
    )
    parser.add_argument("event_type", help="e.g. DYNAMIC_TASK_REQUEST, TASK_COMPLETED")
    parser.add_argument("--task_id", type=int, default=None)
    parser.add_argument("--work_id", type=int, default=None)
    parser.add_argument("--employee_id", type=int, default=None)
    parser.add_argument("--assignment_id", type=int, default=None)
    parser.add_argument("--due_date", type=str, default=None,
                        help="ISO format datetime, e.g. 2026-06-26T18:00:00")

    args = parser.parse_args()

    # Convert CLI string to enum at the boundary
    try:
        event_enum = HospitalEventEnum(args.event_type)
    except ValueError:
        valid = ", ".join(e.value for e in HospitalEventEnum)
        print(f"Unknown event_type '{args.event_type}'. Valid types: {valid}")
        sys.exit(1)

    # Build payload from CLI args (exclude None values)
    payload = {}
    for key in ["task_id", "work_id", "employee_id", "assignment_id"]:
        val = getattr(args, key)
        if val is not None:
            payload[key] = val
    if args.due_date:
        payload["due_date"] = datetime.fromisoformat(args.due_date)

    db = SessionLocal()

    try:
        result = publish_event(
            event_type=event_enum,
            payload=payload,
            db=db,
        )
        print()
        print("=" * 60)
        print("  RESULT")
        print("=" * 60)
        for key, value in result.items():
            print(f"  {key:20s} : {value}")
        print("=" * 60)
    except ValueError as e:
        print(f"\nERROR: {e}")
    finally:
        db.close()
