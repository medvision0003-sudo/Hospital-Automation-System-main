"""
Emergency Response Agent

Receives emergency events, validates them, determines a rule-based
response plan, and dispatches work requests to the Task Management Agent.

Does NOT assign tasks or detect emergencies.
Detection comes from external sources (panic button, nurse input, sensors, etc.).
This agent decides how the hospital should respond.

Architecture:
    EmergencyTypeEnum  ->  EMERGENCY_TO_HOSPITAL_CODE  ->  HospitalCodeEnum
    HospitalCodeEnum   ->  EMERGENCY_RULES             ->  Task list
"""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models.task_master import TaskMaster
from app.models.department import Department
from app.models.agent_action_log import AgentActionLog
from app.models.enums import (
    EmergencyTypeEnum,
    HospitalCodeEnum,
    AgentActionStatusEnum,
    TaskStatusEnum,
    PriorityEnum,
    TaskTypeEnum,
)
from app.agents.task_management_agent import create_work_item
from app.orchestrator.execution import AgentExecutionError
from app.orchestrator.constants import EMERGENCY_RESPONSE_AGENT, ExecutionStatus


# Event-to-Protocol Mapping
# Maps each internal emergency event to the corresponding hospital code.
# This mapping is the single source of truth for the resolution step.

EMERGENCY_TO_HOSPITAL_CODE: dict[EmergencyTypeEnum, HospitalCodeEnum] = {
    EmergencyTypeEnum.PATIENT_COLLAPSE: HospitalCodeEnum.CODE_BLUE,
    EmergencyTypeEnum.FIRE:             HospitalCodeEnum.CODE_RED,
    EmergencyTypeEnum.INFANT_ABDUCTION: HospitalCodeEnum.CODE_PINK,
    EmergencyTypeEnum.ACTIVE_SHOOTER:   HospitalCodeEnum.CODE_SILVER,
    EmergencyTypeEnum.COMBATIVE_PERSON: HospitalCodeEnum.CODE_PURPLE,
    EmergencyTypeEnum.BOMB_THREAT:      HospitalCodeEnum.CODE_BLACK,
    EmergencyTypeEnum.HAZMAT_SPILL:     HospitalCodeEnum.CODE_ORANGE,
    EmergencyTypeEnum.MISSING_PATIENT:  HospitalCodeEnum.CODE_YELLOW,
    EmergencyTypeEnum.EVACUATION_ALERT: HospitalCodeEnum.CODE_GREEN,
    EmergencyTypeEnum.MASS_CASUALTY:    HospitalCodeEnum.CODE_BROWN,
}


# Rule Engine
# Maps each HospitalCodeEnum to the task templates that should be triggered.
# Each entry references a task_name + department_name that must exist in TaskMaster.

EMERGENCY_RULES: dict[HospitalCodeEnum, list[dict]] = {

    HospitalCodeEnum.CODE_BLUE: [
        {"task_name": "RESPOND TO COLLAPSE", "department": "NURSING", "priority": "CRITICAL"},
        {"task_name": "NOTIFY DUTY DOCTOR", "department": "EMERGENCY", "priority": "CRITICAL"},
        {"task_name": "CODE BLUE RESPONSE", "department": "EMERGENCY", "priority": "CRITICAL"},
        {"task_name": "PREPARE CRASH CART", "department": "NURSING", "priority": "CRITICAL"},
    ],

    HospitalCodeEnum.CODE_RED: [
        {"task_name": "EVACUATE AREA", "department": "SECURITY", "priority": "CRITICAL"},
        {"task_name": "NOTIFY FIRE DEPARTMENT", "department": "ADMIN", "priority": "CRITICAL"},
        {"task_name": "SECURE MEDICAL RECORDS", "department": "ADMIN", "priority": "HIGH"},
    ],

    HospitalCodeEnum.CODE_PINK: [
        {"task_name": "LOCKDOWN AREA", "department": "SECURITY", "priority": "CRITICAL"},
        {"task_name": "SECURITY RESPONSE", "department": "SECURITY", "priority": "CRITICAL"},
    ],

    HospitalCodeEnum.CODE_SILVER: [
        {"task_name": "LOCKDOWN AREA", "department": "SECURITY", "priority": "CRITICAL"},
        {"task_name": "SECURITY RESPONSE", "department": "SECURITY", "priority": "CRITICAL"},
    ],

    HospitalCodeEnum.CODE_PURPLE: [
        {"task_name": "SECURITY RESPONSE", "department": "SECURITY", "priority": "CRITICAL"},
        {"task_name": "LOCKDOWN AREA", "department": "SECURITY", "priority": "HIGH"},
    ],

    HospitalCodeEnum.CODE_BLACK: [
        {"task_name": "SECURITY RESPONSE", "department": "SECURITY", "priority": "CRITICAL"},
        {"task_name": "LOCKDOWN AREA", "department": "SECURITY", "priority": "CRITICAL"},
    ],

    HospitalCodeEnum.CODE_ORANGE: [
        {"task_name": "CONTAIN HAZMAT", "department": "MAINTENANCE", "priority": "CRITICAL"},
        {"task_name": "NOTIFY SAFETY OFFICER", "department": "ADMIN", "priority": "HIGH"},
        {"task_name": "ISOLATE AREA", "department": "SECURITY", "priority": "CRITICAL"},
    ],

    HospitalCodeEnum.CODE_YELLOW: [
        {"task_name": "SECURITY RESPONSE", "department": "SECURITY", "priority": "HIGH"},
        {"task_name": "NOTIFY DEPARTMENT HEAD", "department": "ADMIN", "priority": "MEDIUM"},
    ],

    HospitalCodeEnum.CODE_GREEN: [
        {"task_name": "EVACUATE AREA", "department": "SECURITY", "priority": "CRITICAL"},
        {"task_name": "NOTIFY DEPARTMENT HEAD", "department": "ADMIN", "priority": "HIGH"},
    ],

    HospitalCodeEnum.CODE_BROWN: [
        {"task_name": "FIRST AID RESPONSE", "department": "NURSING", "priority": "CRITICAL"},
        {"task_name": "NOTIFY DUTY DOCTOR", "department": "EMERGENCY", "priority": "HIGH"},
        {"task_name": "ACTIVATE TRIAGE", "department": "NURSING", "priority": "CRITICAL"},
    ],
}


# Internal Helpers

def _validate_emergency(
    emergency_type: EmergencyTypeEnum,
    location: str,
    reported_by,
) -> list[str]:
    """Return a list of validation errors (empty = valid)."""
    errors = []

    hospital_code = EMERGENCY_TO_HOSPITAL_CODE.get(emergency_type)
    if hospital_code is None or hospital_code not in EMERGENCY_RULES:
        errors.append(f"Unknown emergency_type: {emergency_type.value}")

    if not location or not str(location).strip():
        errors.append("location is required")

    if not reported_by or not str(reported_by).strip():
        errors.append("reported_by is required")

    return errors


def _generate_response_plan(hospital_code: HospitalCodeEnum) -> list[dict]:
    """Look up the rule engine and return the list of tasks to create."""
    return EMERGENCY_RULES.get(hospital_code, [])


def _resolve_task(task_name: str, department_name: str, priority_str: str, db: Session) -> Optional[TaskMaster]:
    """
    Find the TaskMaster record by task_name + department_name.
    Auto-creates missing task templates if not present.
    """
    task = (
        db.query(TaskMaster)
        .join(Department, TaskMaster.department_id == Department.department_id)
        .filter(
            TaskMaster.task_name == task_name,
            Department.department_name.ilike(department_name),
            TaskMaster.task_state == TaskStatusEnum.ACTIVE,
        )
        .first()
    )
    if task is None:
        dept = db.query(Department).filter(Department.department_name.ilike(department_name)).first()
        if not dept:
            dept = Department(department_name=department_name, status="ACTIVE")
            db.add(dept)
            db.flush()

        p_cat = PriorityEnum.CRITICAL
        if priority_str:
            try:
                p_cat = PriorityEnum(priority_str.upper())
            except ValueError:
                pass

        task = TaskMaster(
            task_name=task_name,
            department_id=dept.department_id,
            estimated_time=15,
            task_state=TaskStatusEnum.ACTIVE,
            priority_category=p_cat,
            task_type=TaskTypeEnum.DYNAMIC,
            required_skill="EMERGENCY_RESPONSE",
        )
        db.add(task)
        db.flush()
    return task


def _create_emergency_tasks(
    plan: list[dict],
    db: Session,
) -> dict:
    """
    Execute the response plan by calling create_work_item for each task.
    Returns a summary of successes and failures.
    """
    import traceback
    work_ids = []
    failures = []

    for entry in plan:
        task_name = entry["task_name"]
        department = entry["department"]
        priority = entry["priority"]

        try:
            task = _resolve_task(task_name, department, priority, db)

            if task is None:
                failures.append(
                    f"Template not found: '{task_name}' in department '{department}'"
                )
                print(f"[EMERGENCY_RESPONSE_AGENT] SKIP: {task_name} -- template not found")
                continue

            est_minutes = task.estimated_time if task.estimated_time else 15
            due_date = datetime.now() + timedelta(minutes=est_minutes)

            result = create_work_item(
                task_id=task.task_id,
                due_date=due_date,
                db=db,
                priority_override=priority,
            )
            work_ids.append(result["work_id"])
            print(f"[EMERGENCY_RESPONSE_AGENT] Created work_id={result['work_id']} for '{task_name}'")
        except Exception as exc:
            failures.append(f"Failed to create '{task_name}': {str(exc)}")
            print(f"[EMERGENCY_RESPONSE_AGENT] FAIL: {task_name} -- {exc}")
            traceback.print_exc()

    return {"work_ids": work_ids, "failures": failures}


def _log_decision(
    db: Session,
    status: AgentActionStatusEnum,
    summary: str,
) -> AgentActionLog:
    """Log the agent's decision for audit trail."""
    action = AgentActionLog(
        event_id=None,
        agent_id=6,  # hardcoded agent id for emergency response agent
        action_type="EMERGENCY_RESPONSE",
        action_timestamp=datetime.now(),
        execution_status=status,
        decision_summary=summary,
    )
    db.add(action)
    db.flush()
    return action


# Public Function

def handle_emergency(
    emergency_type: EmergencyTypeEnum,
    location: str,
    reported_by,
    payload: dict,
    db: Session,
) -> dict:
    """
    Emergency Response Agent -- single public entry point.

    Receives an emergency event, validates it, resolves the hospital
    code protocol, generates a response plan from the rule engine,
    and dispatches work items to the Task Management Agent.

    Args:
        emergency_type:  Type of emergency (from EmergencyTypeEnum).
        location:        Where the emergency occurred (e.g. "WARD_3").
        reported_by:     Who reported it (e.g. "NURSE", "DOCTOR", "SENSOR", or employee ID).
        payload:         Additional context (patient_id, description, etc.).
        db:              SQLAlchemy session.

    Returns:
        Dict with emergency_type, hospital_code, protocol_description,
        tasks_created count, work_ids, and any failures.
    """

    print(f"[EMERGENCY_RESPONSE_AGENT] Received: {emergency_type.value} at {location}")

    # Step 1: Validate
    errors = _validate_emergency(emergency_type, location, reported_by)
    if errors:
        error_msg = "; ".join(errors)
        print(f"[EMERGENCY_RESPONSE_AGENT] Validation FAILED: {error_msg}")
        _log_decision(db, AgentActionStatusEnum.FAILED, f"Validation failed: {error_msg}")
        db.commit()
        raise AgentExecutionError(
            EMERGENCY_RESPONSE_AGENT,
            error_msg,
        )

    # Step 2: Resolve hospital code protocol
    hospital_code = EMERGENCY_TO_HOSPITAL_CODE[emergency_type]
    print(f"[EMERGENCY_RESPONSE_AGENT] Resolved protocol: {hospital_code.value} -- {hospital_code.description}")

    # Step 3: Generate response plan from hospital code
    plan = _generate_response_plan(hospital_code)
    print(f"[EMERGENCY_RESPONSE_AGENT] Response plan: {len(plan)} task(s)")

    if not plan:
        _log_decision(
            db, AgentActionStatusEnum.FAILED,
            f"No response plan defined for {hospital_code.value}",
        )
        db.commit()
        raise AgentExecutionError(
            EMERGENCY_RESPONSE_AGENT,
            f"No response plan for hospital code: {hospital_code.value}",
        )

    # Step 4: Create work items
    task_result = _create_emergency_tasks(plan, db)

    # Step 5: Log decision
    summary = (
        f"{emergency_type.value} ({hospital_code.value}) at {location} "
        f"reported by {reported_by}. "
        f"Created {len(task_result['work_ids'])} task(s). "
        f"Failures: {len(task_result['failures'])}."
    )
    if payload.get("description"):
        summary += f" Description: {payload['description']}"

    status = (
        AgentActionStatusEnum.SUCCESS
        if task_result["work_ids"]
        else AgentActionStatusEnum.FAILED
    )
    _log_decision(db, status, summary)
    db.commit()

    result = {
        "emergency_type": emergency_type.value,
        "hospital_code": hospital_code.value,
        "protocol_description": hospital_code.description,
        "location": location,
        "reported_by": str(reported_by),
        "tasks_created": len(task_result["work_ids"]),
        "work_ids": task_result["work_ids"],
        "workflow": [
            {"agent": EMERGENCY_RESPONSE_AGENT, "status": ExecutionStatus.SUCCESS},
        ],
    }

    if task_result["failures"]:
        result["failures"] = task_result["failures"]

    print(f"[EMERGENCY_RESPONSE_AGENT] Done. {result['tasks_created']} task(s) created.")
    return result
