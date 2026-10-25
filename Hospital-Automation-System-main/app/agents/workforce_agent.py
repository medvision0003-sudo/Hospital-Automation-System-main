"""
Workforce Agent â€” Service Layer
Validates employee availability and provides eligible employees
for task assignment. Does NOT perform task assignment itself.
"""

import argparse
import re
from datetime import datetime, date, timedelta
from typing import Optional

from sqlalchemy import func as sql_func
from sqlalchemy.orm import Session

from app.models.department import Department
from app.models.employee import Employee
from app.models.task_master import TaskMaster
from app.models.department_work_queue import DepartmentWorkQueue
from app.models.task_assignment import TaskAssignment
from app.models.event_log import EventLog
from app.models.agent_action_log import AgentActionLog
from app.models.worker_memory import WorkerMemory
from app.models.worker_checkin import WorkerCheckin
from app.models.shift_roster import ShiftRoster
from app.models.enums import (
    EmploymentStatusEnum,
    CheckinStatusEnum,
    AgentActionStatusEnum,
    AssignmentStatusEnum,
    RosterStatusEnum,
    WorkQueueStatusEnum,
    PriorityEnum,
)
from app.services.worker_memory_service import get_or_create_worker_memory


# Helpers

def _log_agent_action(db: Session, event_id, status, decision_summary, department_id: Optional[int] = None):
    """Insert a row into AgentActionLog for audit."""
    action = AgentActionLog(
        event_id=event_id,
        department_id=department_id,
        agent_id=4,
        action_type="WORKFORCE_CHECK",
        action_timestamp=datetime.now(),
        execution_status=status,
        decision_summary=decision_summary,
    )
    db.add(action)
    db.flush()
    return action


def _log_attendance_event(
    db: Session,
    event_name: str,
    employee_id: int,
    trigger_source: Optional[str],
):
    event = EventLog(
        event_log=event_name,
        source_module=trigger_source or "API",
        employee_id=employee_id,
    )
    db.add(event)
    db.flush()
    return event


def _get_latest_checkin(db: Session, employee_id: int):
    """Return the most recent WorkerCheckin row for an employee, or None."""
    return (
        db.query(WorkerCheckin)
        .filter(WorkerCheckin.employee_id == employee_id)
        .order_by(WorkerCheckin.checkin_time.desc())
        .first()
    )


def _shift_window(roster: ShiftRoster) -> tuple[datetime, datetime]:
    """Return the scheduled shift window, including overnight shifts."""
    shift = roster.shift
    start = datetime.combine(roster.work_date, shift.start_time)
    end = datetime.combine(roster.work_date, shift.end_time)
    if end <= start:
        end += timedelta(days=1)
    return start, end


def _roster_is_current(roster: ShiftRoster, current_time: datetime) -> bool:
    start, end = _shift_window(roster)
    if start <= current_time < end:
        return True
    return bool(
        roster.is_overtime
        and roster.overtime_end_time
        and start <= current_time < roster.overtime_end_time
    )


def _get_today_roster(
    db: Session,
    employee_id: int,
    current_time: Optional[datetime] = None,
):
    """Return the employee's current or next roster entry.

    Active statuses include SCHEDULED, CHECKED_IN, HALF_DAY, and ABSENT
    so that half-day arrivals and absent-then-arrived workers can still
    match a roster entry during check-in. Yesterday's overnight shift is
    included when it is still in progress.
    """
    now = current_time or datetime.now()
    entries = (
        db.query(ShiftRoster)
        .filter(
            ShiftRoster.employee_id == employee_id,
            ShiftRoster.work_date.between(
                now.date() - timedelta(days=1),
                now.date(),
            ),
            ShiftRoster.roster_status.in_([
                RosterStatusEnum.SCHEDULED,
                RosterStatusEnum.CHECKED_IN,
                RosterStatusEnum.HALF_DAY,
                RosterStatusEnum.ABSENT,
                RosterStatusEnum.OVERTIME,
            ]),
        )
        .order_by(ShiftRoster.work_date.desc(), ShiftRoster.roster_id.desc())
        .all()
    )

    current_entries = [
        entry for entry in entries
        if _roster_is_current(entry, now)
    ]
    if current_entries:
        return max(current_entries, key=lambda entry: entry.roster_id)

    upcoming_entries = []
    for entry in entries:
        if entry.work_date != now.date():
            continue
        start, end = _shift_window(entry)
        if start > now and end > now:
            upcoming_entries.append((start, entry))
    if upcoming_entries:
        return min(upcoming_entries, key=lambda value: value[0])[1]

    return None


def _get_rostered_employees(
    db: Session,
    department_id: int,
    current_time: Optional[datetime] = None,
):
    """Return employees whose rostered shift is active in a department.

    Includes SCHEDULED, CHECKED_IN, and HALF_DAY statuses.
    HALF_DAY workers are physically present and eligible for tasks.
    """
    now = current_time or datetime.now()
    entries = (
        db.query(ShiftRoster)
        .join(ShiftRoster.shift)
        .filter(
            ShiftRoster.work_date.between(
                now.date() - timedelta(days=1),
                now.date(),
            ),
            ShiftRoster.roster_status.in_([
                RosterStatusEnum.SCHEDULED,
                RosterStatusEnum.CHECKED_IN,
                RosterStatusEnum.HALF_DAY,
                RosterStatusEnum.OVERTIME,
            ]),
        )
        .join(Employee, Employee.employee_id == ShiftRoster.employee_id)
        .filter(
            Employee.department_id == department_id,
            Employee.availability == EmploymentStatusEnum.ACTIVE,
        )
        .all()
    )
    return [entry for entry in entries if _roster_is_current(entry, now)]


# Public Function 0: checkin_worker

def checkin_worker(
    employee_id: int,
    db: Session,
    device_id: Optional[str] = None,
    current_time: Optional[datetime] = None,
    trigger_source: Optional[str] = None,
) -> dict:
    """
    Check in an employee for their rostered shift.

    Steps:
        1. Validate employee existence and ACTIVE status.
        2. Find today's ShiftRoster entry. If none, fall back gracefully.
        3. Create WorkerCheckin record.
        4. Keep the roster CHECKED_IN through the late window; mark HALF_DAY
           only when check-in is more than the configured half-day threshold
           after shift start.
        5. Return check-in summary with department_id for downstream assignment.
    """

    if current_time is None:
        current_time = datetime.now()
    elif isinstance(current_time, str):
        current_time = datetime.fromisoformat(current_time.replace("Z", "+00:00"))
        if current_time.tzinfo is not None:
            current_time = current_time.astimezone().replace(tzinfo=None)

    print("=" * 60)
    print("  WORKFORCE AGENT -- checkin_worker")
    print("=" * 60)

    # Step 1: Validate employee
    print(f"\n[Step 1] Checking employee {employee_id} exists and is ACTIVE...")

    employee = (
        db.query(Employee)
        .filter(Employee.employee_id == employee_id)
        .first()
    )

    if not employee:
        reason = f"employee_id={employee_id} does not exist"
        print(f"         [FAIL] {reason}")
        action = _log_agent_action(db, None, AgentActionStatusEnum.FAILED, reason)
        db.commit()
        raise ValueError(reason)

    if employee.availability != EmploymentStatusEnum.ACTIVE:
        reason = f"Employee availability is {employee.availability.value}, not ACTIVE"
        print(f"         [FAIL] {reason}")
        action = _log_agent_action(db, None, AgentActionStatusEnum.FAILED, reason)
        db.commit()
        raise ValueError(reason)

    current_checkin = (
        db.query(WorkerCheckin)
        .filter(
            WorkerCheckin.employee_id == employee_id,
            WorkerCheckin.status == CheckinStatusEnum.CHECKED_IN,
        )
        .first()
    )
    if current_checkin:
        reason = f"Employee {employee_id} is already checked in"
        _log_agent_action(db, None, AgentActionStatusEnum.FAILED, reason)
        db.commit()
        raise ValueError(reason)

    print(f"         [OK] {employee.name} (dept={employee.department_id})")

    # Step 2: Find today's roster entry
    print(f"\n[Step 2] Looking up today's roster...")

    roster_entry = _get_today_roster(db, employee_id, current_time)
    shift_id = None
    roster_id = None

    if not roster_entry:
        reason = f"No roster entry for employee {employee_id} today or active overnight shift"
        _log_agent_action(db, None, AgentActionStatusEnum.FAILED, reason)
        db.commit()
        raise ValueError(reason)

    shift_id = roster_entry.shift_id
    roster_id = roster_entry.roster_id
    print(f"         [OK] Found roster_id={roster_id}, shift_id={shift_id}")

    # Step 3: Create WorkerCheckin
    print(f"\n[Step 3] Creating WorkerCheckin record...")

    checkin = WorkerCheckin(
        device_id=device_id or (
            f"{'MANUAL_OVERRIDE' if trigger_source == 'MANUAL_OVERRIDE' else 'CHECKIN'}_"
            f"{employee_id}_{current_time.strftime('%Y%m%d%H%M%S')}"
        ),
        checkin_time=current_time,
        employee_id=employee_id,
        status=CheckinStatusEnum.CHECKED_IN,
    )
    db.add(checkin)
    db.flush()
    print(f"         [OK] Checkin created (device_id={checkin.device_id})")

    attendance_event = _log_attendance_event(
        db,
        "WORKER_CHECKED_IN",
        employee_id,
        trigger_source,
    )

    # Step 4: Determine roster status using grace period
    if roster_entry:
        from app.models.shift import Shift
        shift_obj = db.query(Shift).filter(Shift.shift_id == roster_entry.shift_id).first()

        new_roster_status = RosterStatusEnum.CHECKED_IN

        if shift_obj:
            # Build full datetime from roster work_date and shift start_time
            shift_start_dt = datetime.combine(roster_entry.work_date, shift_obj.start_time)
            from app.services.system_config_service import get_config_value
            grace_minutes = get_config_value(db, "SHIFT_GRACE_PERIOD_MINUTES", 30)
            half_day_minutes = get_config_value(
                db,
                "SHIFT_HALF_DAY_THRESHOLD_MINUTES",
                120,
            )
            half_day_cutoff = shift_start_dt + timedelta(minutes=half_day_minutes)

            if current_time > half_day_cutoff:
                new_roster_status = RosterStatusEnum.HALF_DAY
                print(f"\n[Step 4] Check-in is past {half_day_minutes}-min half-day threshold")
                print(f"         shift_start={shift_start_dt}, half_day_cutoff={half_day_cutoff}")
                print(f"         Updating roster status to HALF_DAY...")
            elif current_time > shift_start_dt + timedelta(minutes=grace_minutes):
                print(f"\n[Step 4] Check-in is late but before the half-day threshold")
                print(f"         shift_start={shift_start_dt}, grace_cutoff={shift_start_dt + timedelta(minutes=grace_minutes)}")
            else:
                print(f"\n[Step 4] Check-in within grace period, setting CHECKED_IN...")
        else:
            print(f"\n[Step 4] No shift object found, defaulting to CHECKED_IN...")

        roster_entry.roster_status = new_roster_status
        print(f"         [OK] roster_id={roster_id} -> {new_roster_status.value}")
    else:
        print(f"\n[Step 4] No roster entry to update -- skipped")

    # Step 5: Log and return
    action = _log_agent_action(
        db, attendance_event.event_id, AgentActionStatusEnum.SUCCESS,
        f"Checked in employee {employee_id} ({employee.name}), "
        f"roster_id={roster_id}, shift_id={shift_id}"
    )
    db.commit()

    result = {
        "employee_id": employee_id,
        "employee_name": employee.name,
        "department_id": employee.department_id,
        "department_name": employee.department.department_name if employee.department else f"DEPT_{employee.department_id}",
        "shift_id": shift_id,
        "roster_id": roster_id,
        "checked_in": True,
        "attendance_source": trigger_source or "API",
        "agent_action_id": action.agent_action_id,
    }

    print()
    print("=" * 60)
    print("  RESULT")
    print("=" * 60)
    for k, v in result.items():
        print(f"  {k:20s} : {v}")
    print("=" * 60)

    return result


# Public Function 1: validate_worker

def validate_worker(employee_id: int, db: Session) -> dict:
    """
    Validate a single employee's existence, active status,
    attendance (latest checkin), and shift match.

    Returns a dict with validation results and the reason if invalid.
    """

    print("=" * 60)
    print("  WORKFORCE AGENT â€” validate_worker")
    print("=" * 60)

    # Step 1: Employee existence
    print(f"\n[Step 1] Checking employee {employee_id} exists...")

    employee = (
        db.query(Employee)
        .filter(Employee.employee_id == employee_id)
        .first()
    )

    if not employee:
        reason = f"employee_id={employee_id} does not exist"
        print(f"         [FAIL] {reason}")
        action = _log_agent_action(db, None, AgentActionStatusEnum.FAILED, reason)
        db.commit()
        return {"valid": False, "employee_id": employee_id, "reason": reason,
                "agent_action_id": action.agent_action_id}

    print(f"         [OK] Found: {employee.name} (dept={employee.department_id})")

    # Step 2: Active status
    print(f"\n[Step 2] Checking status...")

    if employee.availability != EmploymentStatusEnum.ACTIVE:
        reason = f"Employee availability is {employee.availability.value}, not ACTIVE"
        print(f"         [FAIL] {reason}")
        action = _log_agent_action(db, None, AgentActionStatusEnum.FAILED, reason)
        db.commit()
        return {"valid": False, "employee_id": employee_id, "reason": reason,
                "agent_action_id": action.agent_action_id}

    print(f"         [OK] Status = ACTIVE")

    # Step 3: Attendance (latest checkin)
    print(f"\n[Step 3] Checking attendance...")

    latest_checkin = _get_latest_checkin(db, employee_id)

    if not latest_checkin:
        reason = "No checkin record found for this employee"
        print(f"         [FAIL] {reason}")
        action = _log_agent_action(db, None, AgentActionStatusEnum.FAILED, reason)
        db.commit()
        return {"valid": False, "employee_id": employee_id, "reason": reason,
                "agent_action_id": action.agent_action_id}

    if latest_checkin.status != CheckinStatusEnum.CHECKED_IN:
        reason = f"Latest checkin status is {latest_checkin.status.value}, not CHECKED_IN"
        print(f"         [FAIL] {reason}")
        action = _log_agent_action(db, None, AgentActionStatusEnum.FAILED, reason)
        db.commit()
        return {"valid": False, "employee_id": employee_id, "reason": reason,
                "agent_action_id": action.agent_action_id}

    print(f"         [OK] Latest checkin = CHECKED_IN at {latest_checkin.checkin_time}")

    # Step 4: Roster match (roster-only, no static shift fallback)
    print(f"\n[Step 4] Checking roster entry for today...")

    roster_entry = _get_today_roster(db, employee_id)

    if roster_entry:
        print(f"         [OK] Rostered today (roster_id={roster_entry.roster_id}, shift_id={roster_entry.shift_id})")
    else:
        reason = f"No roster entry for employee {employee_id} today"
        print(f"         [FAIL] {reason}")
        action = _log_agent_action(db, None, AgentActionStatusEnum.FAILED, reason)
        db.commit()
        return {"valid": False, "employee_id": employee_id, "reason": reason,
                "agent_action_id": action.agent_action_id}

    # All passed
    action = _log_agent_action(
        db, None, AgentActionStatusEnum.SUCCESS,
        f"Employee {employee_id} ({employee.name}) passed all validations"
    )
    db.commit()

    result = {
        "valid": True,
        "employee_id": employee_id,
        "employee_name": employee.name,
        "department_id": employee.department_id,
        "shift_id": roster_entry.shift_id,
        "checkin_status": latest_checkin.status.value,
        "agent_action_id": action.agent_action_id,
    }

    print(f"\n[Result] VALID")
    print("=" * 60)
    for k, v in result.items():
        print(f"  {k:20s} : {v}")
    print("=" * 60)

    return result


# Public Function 2: get_available_workers

def get_available_workers(department_id: int, db: Session) -> dict:
    """
    Fetch all employees in a department who are:
      - ACTIVE status
      - Current shift matches
      - Latest checkin is CHECKED_IN

    Returns a dict with the list of available employees.
    """

    print("=" * 60)
    print("  WORKFORCE AGENT â€” get_available_workers")
    print("=" * 60)

    # Step 1: Validate department
    print(f"\n[Step 1] Validating department {department_id}...")

    dept = (
        db.query(Department)
        .filter(Department.department_id == department_id)
        .first()
    )

    if not dept:
        reason = f"department_id={department_id} does not exist"
        print(f"         [FAIL] {reason}")
        action = _log_agent_action(db, None, AgentActionStatusEnum.FAILED, reason)
        db.commit()
        return {"available": [], "count": 0, "reason": reason,
                "agent_action_id": action.agent_action_id}

    print(f"         [OK] Department: {dept.department_name}")

    # Step 2: Query eligible employees (roster-only)
    print(f"\n[Step 2] Querying rostered employees...")

    rostered = _get_rostered_employees(db, department_id)
    rostered_ids = {r.employee_id for r in rostered}

    if not rostered_ids:
        reason = f"No employees rostered today in department {department_id}"
        print(f"         [INFO] {reason}")
        action = _log_agent_action(db, None, AgentActionStatusEnum.SUCCESS, reason)
        db.commit()
        return {"department_id": department_id, "department_name": dept.department_name,
                "count": 0, "available": [], "agent_action_id": action.agent_action_id}

    print(f"         Found {len(rostered_ids)} rostered employee(s)")

    # Subquery: latest checkin time per employee
    latest_checkin_sub = (
        db.query(
            WorkerCheckin.employee_id,
            sql_func.max(WorkerCheckin.checkin_time).label("max_checkin")
        )
        .group_by(WorkerCheckin.employee_id)
        .subquery()
    )

    rows = (
        db.query(Employee, WorkerCheckin)
        .join(latest_checkin_sub, Employee.employee_id == latest_checkin_sub.c.employee_id)
        .join(
            WorkerCheckin,
            (WorkerCheckin.employee_id == Employee.employee_id) &
            (WorkerCheckin.checkin_time == latest_checkin_sub.c.max_checkin)
        )
        .filter(
            Employee.department_id == department_id,
            Employee.availability == EmploymentStatusEnum.ACTIVE,
            Employee.employee_id.in_(rostered_ids),
            WorkerCheckin.status == CheckinStatusEnum.CHECKED_IN,
        )
        .all()
    )

    available = []
    for emp, checkin in rows:
        available.append({
            "employee_id": emp.employee_id,
            "name": emp.name,
            "role": emp.role,
            "checkin_time": str(checkin.checkin_time),
        })

    print(f"         Found {len(available)} available employee(s)")
    for w in available:
        print(f"           * {w['name']} (id={w['employee_id']}, role={w['role']})")

    action = _log_agent_action(
        db, None, AgentActionStatusEnum.SUCCESS,
        f"Found {len(available)} available workers in department {department_id}"
    )
    db.commit()

    result = {
        "department_id": department_id,
        "department_name": dept.department_name,
        "count": len(available),
        "available": available,
        "agent_action_id": action.agent_action_id,
    }

    print()
    print("=" * 60)
    print("  RESULT")
    print("=" * 60)
    print(f"  department           : {dept.department_name}")
    print(f"  available_count      : {len(available)}")
    print("=" * 60)

    return result


# Public Function 3: get_worker_metrics

def get_worker_metrics(employee_id: int, db: Session) -> dict:
    """
    Fetch workload and performance metrics from WorkerMemory
    for a specific employee.

    Metrics returned: pending_task, total_task_completed.
    """

    print("=" * 60)
    print("  WORKFORCE AGENT â€” get_worker_metrics")
    print("=" * 60)

    # Step 1: Validate employee exists
    print(f"\n[Step 1] Checking employee {employee_id}...")

    employee = (
        db.query(Employee)
        .filter(Employee.employee_id == employee_id)
        .first()
    )

    if not employee:
        reason = f"employee_id={employee_id} does not exist"
        print(f"         [FAIL] {reason}")
        action = _log_agent_action(db, None, AgentActionStatusEnum.FAILED, reason)
        db.commit()
        return {"found": False, "employee_id": employee_id, "reason": reason,
                "agent_action_id": action.agent_action_id}

    print(f"         [OK] {employee.name}")

    # Step 2: Fetch WorkerMemory
    print(f"\n[Step 2] Fetching worker memory...")

    memory = (
        db.query(WorkerMemory)
        .filter(WorkerMemory.employee_id == employee_id)
        .first()
    )

    if not memory:
        reason = f"No WorkerMemory record for employee_id={employee_id}"
        print(f"         [INFO] {reason}")
        action = _log_agent_action(db, None, AgentActionStatusEnum.SUCCESS, reason)
        db.commit()
        return {
            "found": True,
            "employee_id": employee_id,
            "employee_name": employee.name,
            "has_memory": False,
            "pending_task": 0,
            "total_task_completed": 0,
            "agent_action_id": action.agent_action_id,
        }

    metrics = {
        "found": True,
        "employee_id": employee_id,
        "employee_name": employee.name,
        "has_memory": True,
        "pending_task": memory.pending_task or 0,
        "total_task_completed": memory.total_task_completed or 0,
        "last_updated": str(memory.last_updated) if memory.last_updated else None,
    }

    print(f"         pending_task         = {metrics['pending_task']}")
    print(f"         total_task_completed = {metrics['total_task_completed']}")

    action = _log_agent_action(
        db, None, AgentActionStatusEnum.SUCCESS,
        f"Retrieved metrics for employee {employee_id} ({employee.name})"
    )
    db.commit()
    metrics["agent_action_id"] = action.agent_action_id

    print()
    print("=" * 60)
    print("  RESULT")
    print("=" * 60)
    for k, v in metrics.items():
        print(f"  {k:24s} : {v}")
    print("=" * 60)

    return metrics


# Public Function 4: get_candidate

_SIMILAR_SKILL_ALIASES = {
    "ACLS": {"ACLS", "ADVANCED_CARDIAC_LIFE_SUPPORT", "ADVANCED CARDIAC LIFE SUPPORT", "CARDIAC_LIFE_SUPPORT", "CARDIAC LIFE SUPPORT", "BLS", "BASIC_LIFE_SUPPORT", "BASIC LIFE SUPPORT", "LIFE_SUPPORT", "LIFE SUPPORT"},
    "BLS": {"BLS", "BASIC_LIFE_SUPPORT", "BASIC LIFE SUPPORT", "LIFE_SUPPORT", "LIFE SUPPORT", "ACLS", "ADVANCED_CARDIAC_LIFE_SUPPORT", "ADVANCED CARDIAC LIFE SUPPORT", "CARDIAC_LIFE_SUPPORT", "CARDIAC LIFE SUPPORT"},
    "CPR": {"CPR", "CARDIOPULMONARY_RESUSCITATION", "CARDIOPULMONARY RESUSCITATION"},
    "TRAUMA": {"TRAUMA", "TRAUMA_CARE", "TRAUMA CARE"},
    "EMERGENCY_RESPONSE": {"EMERGENCY_RESPONSE", "EMERGENCY_RESPONSE_CARE", "EMERGENCY", "EMERGENCY CARE"},
    "Triage": {"TRIAGE", "PATIENT_TRIAGE", "PATIENT TRIAGE"},
    "IV": {"IV", "IV_THERAPY", "IV THERAPY", "INTRAVENOUS_THERAPY", "INTRAVENOUS THERAPY"},
}


def _normalize_skills(skill_string: str) -> set:
    """Split a comma-separated skill string into a set of uppercase tokens."""
    if not skill_string:
        return set()
    return {s.strip().upper() for s in skill_string.split(",") if s.strip()}


def _expand_skill_variants(skill: str) -> set[str]:
    """Return a set of canonical and near-synonym variants for a skill value."""
    if not skill:
        return set()

    cleaned = re.sub(r"[^A-Z0-9]+", " ", skill.upper()).strip()
    variants = {cleaned.replace(" ", "_")}
    if cleaned:
        variants.add(cleaned)
        variants.add(cleaned.replace(" ", "_"))

    for alias_key, alias_values in _SIMILAR_SKILL_ALIASES.items():
        if cleaned in alias_values or cleaned == alias_key:
            variants.update(alias_values)

    return variants


def _skills_are_equivalent(required_skill: Optional[str], worker_skill: Optional[str]) -> bool:
    """Return True when a worker's skill is the same as or similar to the task requirement."""
    required_tokens = _normalize_skills(required_skill)
    worker_tokens = _normalize_skills(worker_skill)

    if not required_tokens or not worker_tokens:
        return False

    if required_tokens & worker_tokens:
        return True

    required_variants = set()
    worker_variants = set()
    for token in required_tokens:
        required_variants.update(_expand_skill_variants(token))
    for token in worker_tokens:
        worker_variants.update(_expand_skill_variants(token))

    if required_variants & worker_variants:
        return True

    for req in required_variants:
        for worker in worker_variants:
            if req in worker or worker in req:
                return True
    return False


def _build_candidate_result(
    candidates: list,
    required_skill=None,
    escalation_required=False,
    escalation_type=None,
    reason="Success",
    **extra,
):
    """Build the stable return dict that every get_candidate branch must use."""
    result = {
        "candidates": candidates,
        "required_skill": required_skill,
        "escalation_required": escalation_required,
        "escalation_type": escalation_type,
        "reason": reason,
    }
    result.update(extra)
    return result


def get_candidate(
    department_id: int,
    db: Session,
    shift_id: Optional[int] = None,
    allow_shift_end_buffer: bool = True,
    current_time: Optional[datetime] = None,
    task_id: Optional[int] = None,
) -> dict:
    """
    Full workforce pipeline:
      1. Validate department
      2. Find all available workers (ACTIVE + shift + CHECKED_IN)
      3. Attach WorkerMemory metrics to each
      4. Apply 15-minute shift-end buffer (exclude workers near end of shift)
      5. Apply skill filtering when task has a required_skill
         - Static token match (ANY intersection)
         - Historical experience fallback (distinct completed assignments)
         - Escalation if no qualified candidate
      6. Return stable candidate result dict

    When shift_id is provided, filters roster to that specific shift
    and returns shift context (total_shift_rostered, checked_in_count,
    shift_name) for fair share calculation upstream.

    When allow_shift_end_buffer is True (default), workers whose shift
    ends within 15 minutes are excluded from the candidate list.
    Set to False for emergency assignments that override the buffer.

    When task_id is provided, looks up the TaskMaster to check for
    required_skill. If the task needs a specific skill, only workers
    matching that skill (static profile or historical experience) are
    returned. If no match is found, returns an escalation result.

    The Assignment Agent or Orchestrator decides who to pick.
    """

    if current_time is None:
        current_time = datetime.now()

    print("=" * 60)
    print("  WORKFORCE AGENT -- get_candidate")
    print("=" * 60)

    # Step 1: Validate department
    print(f"\n[Step 1] Validating department {department_id}...")

    dept = (
        db.query(Department)
        .filter(Department.department_id == department_id)
        .first()
    )

    if not dept:
        reason = f"department_id={department_id} does not exist"
        print(f"         [FAIL] {reason}")
        action = _log_agent_action(db, None, AgentActionStatusEnum.FAILED, reason)
        db.commit()
        raise ValueError(reason)

    print(f"         [OK] {dept.department_name}")

    # Step 2: Get available workers (roster-only, optionally shift-scoped)
    # HALF_DAY workers are physically present and eligible for tasks
    print(f"\n[Step 2] Finding rostered employees...")

    rostered = _get_rostered_employees(db, department_id, current_time)
    if shift_id is not None:
        rostered = [roster for roster in rostered if roster.shift_id == shift_id]
        print(f"         [INFO] Filtering to shift_id={shift_id}")

    rostered_ids = {r.employee_id for r in rostered}

    # Build shift context when shift_id is provided
    # HALF_DAY counts as checked-in for fair-share math since they are physically present
    shift_context = {}
    if shift_id is not None:
        from app.models.shift import Shift
        shift_obj = db.query(Shift).filter(Shift.shift_id == shift_id).first()
        shift_name = shift_obj.shift_name if shift_obj else f"shift_{shift_id}"

        total_shift_rostered = len(rostered)
        checked_in_count = sum(
            1 for r in rostered
            if r.roster_status in (RosterStatusEnum.CHECKED_IN, RosterStatusEnum.HALF_DAY, RosterStatusEnum.OVERTIME)
        )
        shift_context = {
            "shift_id": shift_id,
            "shift_name": shift_name,
            "total_shift_rostered": total_shift_rostered,
            "checked_in_count": checked_in_count,
        }
        print(f"         [INFO] Shift: {shift_name} | rostered={total_shift_rostered} | checked_in={checked_in_count}")

    if not rostered_ids:
        reason = "No eligible checked-in worker is currently available."
        print(f"         [FAIL] {reason}")
        _log_agent_action(db, None, AgentActionStatusEnum.FAILED, reason, department_id=department_id)
        db.commit()
        return _build_candidate_result(
            [], escalation_required=True,
            escalation_type="NO_AVAILABLE_WORKER", reason=reason,
            department_id=department_id, department_name=dept.department_name,
            **shift_context,
        )

    print(f"         Found {len(rostered_ids)} rostered employee(s)")

    # Apply 15-minute shift-end buffer
    if allow_shift_end_buffer:
        from app.models.shift import Shift
        buffer_cutoff = current_time + timedelta(minutes=15)
        excluded_ids = set()

        for roster in rostered:
            # Overtime workers bypass the shift-end buffer entirely
            if roster.is_overtime or roster.roster_status == RosterStatusEnum.OVERTIME:
                print(f"         [BUFFER] Skipping overtime worker employee_id={roster.employee_id}")
                continue

            shift_obj = db.query(Shift).filter(Shift.shift_id == roster.shift_id).first()
            if not shift_obj:
                continue
            shift_end_dt = datetime.combine(roster.work_date, shift_obj.end_time)
            shift_start_dt = datetime.combine(roster.work_date, shift_obj.start_time)
            if shift_end_dt <= shift_start_dt:
                shift_end_dt += timedelta(days=1)

            if shift_end_dt <= buffer_cutoff:
                excluded_ids.add(roster.employee_id)
                print(f"         [BUFFER] Excluding employee_id={roster.employee_id} (shift ends at {shift_end_dt})")

        if excluded_ids:
            rostered_ids -= excluded_ids
            print(f"         [BUFFER] {len(excluded_ids)} worker(s) excluded, {len(rostered_ids)} remaining")

    if not rostered_ids:
        reason = "No eligible checked-in worker is currently available."
        print(f"         [FAIL] {reason}")
        _log_agent_action(db, None, AgentActionStatusEnum.FAILED, reason, department_id=department_id)
        db.commit()
        return _build_candidate_result(
            [], escalation_required=True,
            escalation_type="NO_AVAILABLE_WORKER", reason=reason,
            department_id=department_id, department_name=dept.department_name,
            **shift_context,
        )

    latest_checkin_sub = (
        db.query(
            WorkerCheckin.employee_id,
            sql_func.max(WorkerCheckin.checkin_time).label("max_checkin")
        )
        .group_by(WorkerCheckin.employee_id)
        .subquery()
    )

    rows = (
        db.query(Employee, WorkerCheckin)
        .join(latest_checkin_sub, Employee.employee_id == latest_checkin_sub.c.employee_id)
        .join(
            WorkerCheckin,
            (WorkerCheckin.employee_id == Employee.employee_id) &
            (WorkerCheckin.checkin_time == latest_checkin_sub.c.max_checkin)
        )
        .filter(
            Employee.department_id == department_id,
            Employee.availability == EmploymentStatusEnum.ACTIVE,
            Employee.employee_id.in_(rostered_ids),
            WorkerCheckin.status == CheckinStatusEnum.CHECKED_IN,
        )
        .all()
    )

    if not rows:
        reason = "No eligible checked-in worker is currently available."
        print(f"         [FAIL] {reason}")
        _log_agent_action(db, None, AgentActionStatusEnum.FAILED, reason, department_id=department_id)
        db.commit()
        return _build_candidate_result(
            [], escalation_required=True,
            escalation_type="NO_AVAILABLE_WORKER", reason=reason,
            department_id=department_id, department_name=dept.department_name,
            **shift_context,
        )

    print(f"         Found {len(rows)} available employee(s)")

    # Step 3: Attach metrics
    print(f"\n[Step 3] Attaching WorkerMemory metrics...")

    all_candidates = []
    for emp, checkin in rows:
        memory = (
            db.query(WorkerMemory)
            .filter(WorkerMemory.employee_id == emp.employee_id)
            .first()
        )

        candidate = {
            "employee_id": emp.employee_id,
            "name": emp.name,
            "role": emp.role,
            "department_id": emp.department_id,
            "skill": emp.skill,
            "experience_years": emp.experience_years or 0,
            "checkin_time": str(checkin.checkin_time),
            "pending_task": memory.pending_task if memory else 0,
            "total_task_completed": memory.total_task_completed if memory else 0,
        }
        all_candidates.append(candidate)

        status = "has metrics" if memory else "no memory record"
        print(f"         * {emp.name} (id={emp.employee_id}) -- {status}")

    # Step 4: Apply task role and skill requirements.
    print(f"\n[Step 4] Applying role and skill filters...")
    task_obj = None
    required_skill_raw = None
    required_role_raw = None
    if task_id is not None:
        task_obj = db.query(TaskMaster).filter(TaskMaster.task_id == task_id).first()
        if task_obj:
            required_skill_raw = task_obj.required_skill
            required_role_raw = task_obj.required_role

    required_role = required_role_raw.strip() if required_role_raw else None
    if required_role:
        role_candidates = [
            candidate
            for candidate in all_candidates
            if candidate["role"]
            and candidate["role"].strip().casefold() == required_role.casefold()
        ]
        if not role_candidates:
            reason = f"No available worker has the required role '{required_role}'."
            print(f"         [ESCALATION] {reason}")
            _log_agent_action(
                db, None, AgentActionStatusEnum.FAILED,
                f"HUMAN_REVIEW_REQUIRED: {reason}",
                department_id=department_id,
            )
            db.commit()
            result = _build_candidate_result(
                [],
                escalation_required=True,
                escalation_type="HUMAN_REVIEW_REQUIRED",
                reason=reason,
                required_role=required_role,
                department_id=department_id,
                department_name=dept.department_name,
            )
            result.update(shift_context)
            return result
        all_candidates = role_candidates

    required_tokens = _normalize_skills(required_skill_raw)
    normalized_skill = required_skill_raw.strip().upper() if required_skill_raw else None

    if not required_tokens:
        # No skill required: all available workers are candidates
        print(f"         [INFO] No required_skill -- returning all available workers")
        for c in all_candidates:
            c["skill_match"] = False
            c["historical_match"] = False
            c["match_source"] = "NO_SKILL_REQUIRED"

        action = _log_agent_action(
            db, None, AgentActionStatusEnum.SUCCESS,
            f"Returned {len(all_candidates)} candidates for department {department_id} ({dept.department_name})"
        )
        db.commit()

        result = _build_candidate_result(
            all_candidates, required_skill=None,
            required_role=required_role,
            department_id=department_id, department_name=dept.department_name,
            candidate_count=len(all_candidates),
            agent_action_id=action.agent_action_id,
        )
        result.update(shift_context)

        print()
        print("=" * 60)
        print("  RESULT")
        print("=" * 60)
        print(f"  department           : {dept.department_name}")
        print(f"  candidate_count      : {len(all_candidates)}")
        if shift_context:
            print(f"  shift                : {shift_context.get('shift_name')}")
            print(f"  total_shift_rostered : {shift_context.get('total_shift_rostered')}")
            print(f"  checked_in_count     : {shift_context.get('checked_in_count')}")
        for c in all_candidates:
            print(f"    -> {c['name']:20s}  pending={c['pending_task']}  completed={c['total_task_completed']}")
        print("=" * 60)

        return result

    # Required skill exists: apply static token match (ANY intersection)
    print(f"         [INFO] Required skill tokens: {required_tokens}")

    static_matches = []
    for c in all_candidates:
        worker_tokens = _normalize_skills(c.get("skill", ""))
        if required_tokens & worker_tokens:
            c["skill_match"] = True
            c["historical_match"] = False
            c["match_source"] = "STATIC_PROFILE"
            static_matches.append(c)

    if static_matches:
        print(f"         [OK] {len(static_matches)} static skill match(es) found")
        action = _log_agent_action(
            db, None, AgentActionStatusEnum.SUCCESS,
            f"Returned {len(static_matches)} STATIC_PROFILE candidates for dept {department_id}, skill={normalized_skill}"
        )
        db.commit()

        result = _build_candidate_result(
            static_matches, required_skill=normalized_skill,
            required_role=required_role,
            department_id=department_id, department_name=dept.department_name,
            candidate_count=len(static_matches),
            agent_action_id=action.agent_action_id,
        )
        result.update(shift_context)
        return result

    # No static match: allow similar-skill reassignments before escalating.
    print(f"         [INFO] No static skill match -- checking similar skills...")
    similar_matches = []
    for c in all_candidates:
        if _skills_are_equivalent(normalized_skill, c.get("skill", "")):
            c["skill_match"] = False
            c["historical_match"] = False
            c["match_source"] = "SIMILAR_SKILL"
            similar_matches.append(c)

    if similar_matches:
        print(f"         [OK] {len(similar_matches)} similar-skill candidate(s) found")
        action = _log_agent_action(
            db, None, AgentActionStatusEnum.SUCCESS,
            f"Returned {len(similar_matches)} SIMILAR_SKILL candidates for dept {department_id}, skill={normalized_skill}"
        )
        db.commit()

        result = _build_candidate_result(
            similar_matches, required_skill=normalized_skill,
            required_role=required_role,
            department_id=department_id, department_name=dept.department_name,
            candidate_count=len(similar_matches),
            agent_action_id=action.agent_action_id,
        )
        result.update(shift_context)
        return result

    # No similar match: historical experience fallback (distinct employee_ids)
    print(f"         [INFO] No similar skill match -- checking historical experience...")

    available_ids = [c["employee_id"] for c in all_candidates]

    historical_ids = (
        db.query(TaskAssignment.employee_id)
        .join(DepartmentWorkQueue, DepartmentWorkQueue.work_id == TaskAssignment.work_id)
        .filter(
            DepartmentWorkQueue.task_id == task_id,
            TaskAssignment.assignment_status == AssignmentStatusEnum.COMPLETED,
            TaskAssignment.employee_id.in_(available_ids),
        )
        .distinct()
        .all()
    )
    historical_employee_ids = {row[0] for row in historical_ids}

    if historical_employee_ids:
        historical_matches = []
        for c in all_candidates:
            if c["employee_id"] in historical_employee_ids:
                c["skill_match"] = False
                c["historical_match"] = True
                c["match_source"] = "HISTORICAL_EXPERIENCE"
                historical_matches.append(c)

        print(f"         [OK] {len(historical_matches)} historical match(es) found")
        action = _log_agent_action(
            db, None, AgentActionStatusEnum.SUCCESS,
            f"Returned {len(historical_matches)} HISTORICAL_EXPERIENCE candidates for dept {department_id}, skill={normalized_skill}"
        )
        db.commit()

        result = _build_candidate_result(
            historical_matches, required_skill=normalized_skill,
            required_role=required_role,
            department_id=department_id, department_name=dept.department_name,
            candidate_count=len(historical_matches),
            agent_action_id=action.agent_action_id,
        )
        result.update(shift_context)
        return result

    # No historical match either: escalation
    reason = f"No available worker has the required skill or prior experience. SKILL={normalized_skill}"
    print(f"         [ESCALATION] {reason}")
    _log_agent_action(
        db, None, AgentActionStatusEnum.FAILED,
        f"HUMAN_REVIEW_REQUIRED: {reason}",
        department_id=department_id,
    )
    db.commit()

    result = _build_candidate_result(
        [], required_skill=normalized_skill,
        required_role=required_role,
        escalation_required=True, escalation_type="HUMAN_REVIEW_REQUIRED",
        reason=reason,
        department_id=department_id, department_name=dept.department_name,
    )
    result.update(shift_context)
    return result



# Public Function 5: update_worker_task_metrics

def update_worker_task_metrics(
    employee_id: Optional[int],
    new_status: str,
    db: Session,
) -> dict:
    """
    Update WorkerMemory metrics for an employee when a task is completed or cancelled.
    """
    print("=" * 60)
    print("  WORKFORCE AGENT -- update_worker_task_metrics")
    print("=" * 60)

    if not employee_id:
        reason = "No employee_id provided for metrics update"
        print(f"         [WARNING] {reason}")
        return {"updated": False, "reason": reason}

    print(f"\n[Step 1] Fetching worker memory for employee {employee_id}...")
    memory = get_or_create_worker_memory(db, employee_id)
    old_pending = memory.pending_task or 0
    old_completed = memory.total_task_completed or 0
    memory.pending_task = (
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
    memory.total_task_completed = (
        db.query(TaskAssignment)
        .filter(
            TaskAssignment.employee_id == employee_id,
            TaskAssignment.assignment_status == AssignmentStatusEnum.COMPLETED,
        )
        .count()
    )

    decision_summary = (
        f"Updated WorkerMemory for employee {employee_id}: "
        f"pending={old_pending}->{memory.pending_task}, "
        f"completed={old_completed}->{memory.total_task_completed} "
        f"(new status={new_status})"
    )
    print(f"         [OK] {decision_summary}")

    # Audit logging
    action = _log_agent_action(
        db,
        event_id=None,
        status=AgentActionStatusEnum.SUCCESS,
        decision_summary=decision_summary,
    )
    db.commit()

    print()
    print("=" * 60)
    print("  RESULT")
    print("=" * 60)
    print(f"  employee_id          : {employee_id}")
    print(f"  pending_task         : {memory.pending_task}")
    print(f"  total_task_completed : {memory.total_task_completed}")
    print("=" * 60)

    return {
        "employee_id": employee_id,
        "pending_task": memory.pending_task,
        "total_task_completed": memory.total_task_completed,
        "agent_action_id": action.agent_action_id,
    }


# Public Function 6: checkout_worker

def checkout_worker(
    employee_id: int,
    db: Session,
    current_time: Optional[datetime] = None,
    trigger_source: Optional[str] = None,
    incomplete_task_action: str = "REASSIGN",
) -> dict:
    """
    Manually check out an employee.

    Steps:
        1. Find the latest WorkerCheckin for this employee.
        2. Set checkin status to CHECKED_OUT with checkout_time.
        3. Find active roster entry (do NOT complete it here).
        4. Delegate to handle_shift_end for roster status management.
    """
    print("=" * 60)
    print("  WORKFORCE AGENT -- checkout_worker")
    print("=" * 60)

    if isinstance(current_time, str):
        current_time = datetime.fromisoformat(current_time.replace("Z", "+00:00"))
        if current_time.tzinfo is not None:
            current_time = current_time.astimezone().replace(tzinfo=None)
    current_time = current_time or datetime.now()
    incomplete_task_action = incomplete_task_action.upper()
    if incomplete_task_action not in {"REASSIGN", "KEEP_PENDING"}:
        raise ValueError("incomplete_task_action must be REASSIGN or KEEP_PENDING")

    print(f"\n[Step 1] Finding latest checkin for employee {employee_id}...")
    latest_checkin = _get_latest_checkin(db, employee_id)

    if not latest_checkin:
        reason = f"No checkin record found for employee_id={employee_id}"
        print(f"         [FAIL] {reason}")
        raise ValueError(reason)

    if latest_checkin.status != CheckinStatusEnum.CHECKED_IN:
        reason = f"Employee {employee_id} is not currently checked in (status={latest_checkin.status.value})"
        print(f"         [FAIL] {reason}")
        raise ValueError(reason)

    print(f"         [OK] Found checkin (device_id={latest_checkin.device_id})")

    # Step 2: Mark checkout
    print(f"\n[Step 2] Setting CHECKED_OUT status...")
    latest_checkin.status = CheckinStatusEnum.CHECKED_OUT
    if current_time < latest_checkin.checkin_time:
        raise ValueError("Check-out time cannot be earlier than check-in time")
    latest_checkin.checkout_time = current_time
    print(f"         [OK] checkout_time={latest_checkin.checkout_time}")

    attendance_event = _log_attendance_event(
        db,
        "WORKER_CHECKED_OUT",
        employee_id,
        trigger_source,
    )

    # Step 3: Find active roster (but do NOT set COMPLETED here)
    print(f"\n[Step 3] Finding active roster entry...")
    roster_candidates = (
        db.query(ShiftRoster)
        .filter(
            ShiftRoster.employee_id == employee_id,
            ShiftRoster.work_date.between(
                latest_checkin.checkin_time.date() - timedelta(days=1),
                latest_checkin.checkin_time.date(),
            ),
            ShiftRoster.roster_status.in_([
                RosterStatusEnum.CHECKED_IN,
                RosterStatusEnum.HALF_DAY,
                RosterStatusEnum.OVERTIME,
            ]),
        )
        .order_by(ShiftRoster.roster_id.desc())
        .all()
    )
    roster_entry = next(
        (
            roster for roster in roster_candidates
            if _roster_is_current(roster, latest_checkin.checkin_time)
        ),
        None,
    )

    roster_id = None
    if roster_entry:
        roster_id = roster_entry.roster_id
        print(f"         [OK] Found roster_id={roster_id} (status={roster_entry.roster_status.value})")
    else:
        print(f"         [INFO] No active roster entry found")

    # Step 4: release incomplete work before closing the roster.
    active_assignments = (
        db.query(TaskAssignment)
        .filter(
            TaskAssignment.employee_id == employee_id,
            TaskAssignment.assignment_status.in_([
                AssignmentStatusEnum.ASSIGNED,
                AssignmentStatusEnum.IN_PROGRESS,
            ]),
        )
        .all()
    )
    incomplete_work_ids = [assignment.work_id for assignment in active_assignments]
    reassigned_work_ids = []
    pending_work_ids = []
    for assignment in active_assignments:
        from app.agents.assignment_agent import preempt_assignment
        preempt_assignment(
            assignment.assignment_id,
            db,
            reason="Worker checked out; incomplete task returned for handover.",
            source_module="WORKFORCE_AGENT",
        )

    if incomplete_task_action == "REASSIGN" and incomplete_work_ids:
        from app.agents.assignment_agent import run_assignment_cycle
        from app.orchestrator.constants import AssignmentTrigger

        department_ids = {
            work.department_id
            for work in db.query(DepartmentWorkQueue)
            .filter(DepartmentWorkQueue.work_id.in_(incomplete_work_ids))
            .all()
        }
        for department_id in department_ids:
            run_assignment_cycle(
                department_id=department_id,
                db=db,
                trigger=AssignmentTrigger.NEW_TASK,
                work_ids=incomplete_work_ids,
                current_time=current_time,
            )

    for work_id in incomplete_work_ids:
        active_replacement = (
            db.query(TaskAssignment)
            .filter(
                TaskAssignment.work_id == work_id,
                TaskAssignment.assignment_status.in_([
                    AssignmentStatusEnum.ASSIGNED,
                    AssignmentStatusEnum.IN_PROGRESS,
                ]),
                TaskAssignment.employee_id != employee_id,
            )
            .first()
        )
        if active_replacement:
            reassigned_work_ids.append(work_id)
        else:
            pending_work_ids.append(work_id)

    # Step 5: Delegate shift-end handling after incomplete assignments are released.
    print(f"\n[Step 4] Running handle_shift_end...")
    if roster_entry:
        cleanup_result = handle_shift_end(roster_entry.roster_id, db)
    else:
        cleanup_result = {"released_count": 0, "status": "NO_ROSTER"}

    action = _log_agent_action(
        db, attendance_event.event_id, AgentActionStatusEnum.SUCCESS,
        f"Checked out employee {employee_id}, roster_id={roster_id}, "
        f"handover_status={cleanup_result.get('status', 'N/A')}"
    )
    db.commit()

    result = {
        "employee_id": employee_id,
        "roster_id": roster_id,
        "checkout_time": str(latest_checkin.checkout_time),
        "work_duration_minutes": int(
            (latest_checkin.checkout_time - latest_checkin.checkin_time).total_seconds() // 60
        ),
        "released_assignments": len(incomplete_work_ids),
        "incomplete_work_ids": incomplete_work_ids,
        "reassigned_work_ids": reassigned_work_ids,
        "pending_work_ids": pending_work_ids,
        "handover_status": (
            "REASSIGNED" if reassigned_work_ids else
            "PENDING" if pending_work_ids else
            cleanup_result.get("status", "N/A")
        ),
        "attendance_source": trigger_source or "API",
        "agent_action_id": action.agent_action_id,
    }

    print()
    print("=" * 60)
    print("  RESULT")
    print("=" * 60)
    for k, v in result.items():
        print(f"  {k:24s} : {v}")
    print("=" * 60)

    return result


# NOTE: Overload detection (WORKER_OVERLOAD_DETECTED) is raised by the
# workload watcher in outbox_dispatcher.py, which is workforce-adjacent.
# Overload correction (preempting and rebalancing active assignments)
# lives in assignment_agent.rebalance_overloaded_worker because it
# mutates task assignments, which is the Assignment Agent's domain.


# Public Function 7: handle_shift_end

def handle_shift_end(roster_id: int, db: Session) -> dict:
    """
    Handle shift-end cleanup for a roster entry.

    Behavior depends on active task state:
        A) No active tasks: Complete roster immediately.
        B) Only IN_PROGRESS tasks: Keep roster active (worker finishing work).
           Log an informational audit.
        C) ASSIGNED tasks exist: Create a SHIFT_HANDOVER_REVIEW ApprovalRequest
           for supervisor decision (overtime vs preempt). Do NOT complete roster.

    Called by:
        - checkout_worker (manual checkout)
        - handle_shift_change_adapter (background watcher)
    """
    import json
    import uuid
    from app.models.department_work_queue import DepartmentWorkQueue
    from app.models.approval_request import ApprovalRequest

    print("=" * 60)
    print("  WORKFORCE AGENT -- handle_shift_end")
    print("=" * 60)

    print(f"\n[Step 1] Loading roster_id={roster_id}...")
    roster = db.query(ShiftRoster).filter(ShiftRoster.roster_id == roster_id).first()
    if not roster:
        reason = f"roster_id={roster_id} not found"
        print(f"         [FAIL] {reason}")
        raise ValueError(reason)

    employee_id = roster.employee_id

    # Step 2: Find active assignments for this employee
    print(f"\n[Step 2] Querying active assignments for employee {employee_id}...")
    active_assignments = (
        db.query(TaskAssignment)
        .filter(
            TaskAssignment.employee_id == employee_id,
            TaskAssignment.assignment_status.in_([
                AssignmentStatusEnum.ASSIGNED,
                AssignmentStatusEnum.IN_PROGRESS,
            ]),
        )
        .all()
    )

    # Separate ASSIGNED (unstarted) vs IN_PROGRESS (active) tasks
    assigned_tasks = [a for a in active_assignments if a.assignment_status == AssignmentStatusEnum.ASSIGNED]
    in_progress_tasks = [a for a in active_assignments if a.assignment_status == AssignmentStatusEnum.IN_PROGRESS]

    assigned_work_ids = [a.work_id for a in assigned_tasks]
    in_progress_work_ids = [a.work_id for a in in_progress_tasks]

    print(f"         ASSIGNED tasks: {len(assigned_tasks)} (work_ids={assigned_work_ids})")
    print(f"         IN_PROGRESS tasks: {len(in_progress_tasks)} (work_ids={in_progress_work_ids})")

    # Path A: No active tasks at all - complete roster immediately
    if not active_assignments:
        if roster.roster_status in (RosterStatusEnum.CHECKED_IN, RosterStatusEnum.HALF_DAY, RosterStatusEnum.SCHEDULED):
            roster.roster_status = RosterStatusEnum.COMPLETED
            print(f"         [OK] roster_id={roster_id} -> COMPLETED (no active tasks)")

        # Recalculate pending_task
        memory = (
            db.query(WorkerMemory)
            .filter(WorkerMemory.employee_id == employee_id)
            .first()
        )
        if memory:
            memory.pending_task = 0

        db.flush()
        return {
            "roster_id": roster_id,
            "employee_id": employee_id,
            "released_count": 0,
            "status": "COMPLETED",
        }

    # Path B: Only IN_PROGRESS tasks, no ASSIGNED tasks
    # Worker is actively working; keep roster active, log informational audit
    if not assigned_tasks and in_progress_tasks:
        print(f"         [INFO] Only IN_PROGRESS tasks remain. Keeping roster active.")
        _log_agent_action(
            db, None, AgentActionStatusEnum.SUCCESS,
            f"Shift end for roster_id={roster_id}: {len(in_progress_tasks)} IN_PROGRESS task(s) remain. "
            f"Worker continues until completion. work_ids={in_progress_work_ids}"
        )
        db.flush()
        return {
            "roster_id": roster_id,
            "employee_id": employee_id,
            "released_count": 0,
            "status": "PENDING_IN_PROGRESS",
            "in_progress_work_ids": in_progress_work_ids,
        }

    # Path C: ASSIGNED tasks exist - create SHIFT_HANDOVER_REVIEW escalation
    # Supervisor must choose: Grant Overtime (Choice A) or Preempt & Carry Forward (Choice B)
    print(f"\n[Step 3] Creating SHIFT_HANDOVER_REVIEW approval request...")

    # Resolve department_id from assigned task work items
    department_id = None
    if assigned_work_ids:
        work_item = (
            db.query(DepartmentWorkQueue)
            .filter(DepartmentWorkQueue.work_id == assigned_work_ids[0])
            .first()
        )
        if work_item:
            department_id = work_item.department_id

    # Resolve employee name for context
    employee = db.query(Employee).filter(Employee.employee_id == employee_id).first()
    employee_name = employee.name if employee else f"employee_{employee_id}"
    dept_name = ""
    if department_id:
        from app.models.department import Department
        dept = db.query(Department).filter(Department.department_id == department_id).first()
        dept_name = dept.department_name if dept else f"dept_{department_id}"

    # Resolve shift end time for context
    from app.models.shift import Shift
    shift_obj = db.query(Shift).filter(Shift.shift_id == roster.shift_id).first()
    shift_end_time = None
    if shift_obj:
        shift_end_dt = datetime.combine(roster.work_date, shift_obj.end_time)
        shift_start_dt = datetime.combine(roster.work_date, shift_obj.start_time)
        if shift_end_dt <= shift_start_dt:
            shift_end_dt += timedelta(days=1)
        shift_end_time = shift_end_dt.isoformat()

    context = {
        "roster_id": roster_id,
        "employee_id": employee_id,
        "employee_name": employee_name,
        "department_id": department_id,
        "department_name": dept_name,
        "assigned_work_ids": assigned_work_ids,
        "in_progress_work_ids": in_progress_work_ids,
        "shift_end_time": shift_end_time,
    }

    approval = ApprovalRequest(
        workflow_id=str(uuid.uuid4()),
        sensitive_action="SHIFT_HANDOVER_REVIEW",
        rationale=(
            f"Shift ending for {employee_name} (dept: {dept_name}). "
            f"{len(assigned_tasks)} unstarted ASSIGNED task(s) and "
            f"{len(in_progress_tasks)} IN_PROGRESS task(s) remain. "
            f"Supervisor action required: grant overtime or preempt assigned tasks."
        ),
        status="PENDING",
        context_state_json=json.dumps(context, default=str),
    )
    db.add(approval)
    db.flush()

    print(f"         [OK] Created ApprovalRequest approval_id={approval.approval_id}")
    print(f"         [OK] workflow_id={approval.workflow_id}")

    _log_agent_action(
        db, None, AgentActionStatusEnum.PENDING,
        f"SHIFT_HANDOVER_REVIEW: roster_id={roster_id}, employee={employee_name}, "
        f"assigned_work_ids={assigned_work_ids}, in_progress_work_ids={in_progress_work_ids}, "
        f"approval_id={approval.approval_id}",
        department_id=department_id,
    )

    db.flush()

    return {
        "roster_id": roster_id,
        "employee_id": employee_id,
        "released_count": 0,
        "status": "PENDING_HUMAN_APPROVAL",
        "approval_id": approval.approval_id,
        "assigned_work_ids": assigned_work_ids,
        "in_progress_work_ids": in_progress_work_ids,
    }


# Public Function 8: mark_worker_absent

def mark_worker_absent(roster_id: int, db: Session) -> dict:
    """
    Transition a roster entry to ABSENT status.

    Called by the absentee watcher when a worker has not checked in
    within 30 minutes of their shift start time.
    """
    print("=" * 60)
    print("  WORKFORCE AGENT -- mark_worker_absent")
    print("=" * 60)

    roster = db.query(ShiftRoster).filter(ShiftRoster.roster_id == roster_id).first()
    if not roster:
        reason = f"roster_id={roster_id} not found"
        print(f"         [FAIL] {reason}")
        raise ValueError(reason)

    old_status = roster.roster_status.value
    roster.roster_status = RosterStatusEnum.ABSENT

    released_work_ids = []
    assigned_work = (
        db.query(TaskAssignment)
        .filter(
            TaskAssignment.employee_id == roster.employee_id,
            TaskAssignment.assignment_status == AssignmentStatusEnum.ASSIGNED,
        )
        .all()
    )
    for assignment in assigned_work:
        assignment.assignment_status = AssignmentStatusEnum.PREEMPTED
        work_item = db.query(DepartmentWorkQueue).filter(
            DepartmentWorkQueue.work_id == assignment.work_id
        ).first()
        if work_item and work_item.queue_status == WorkQueueStatusEnum.ASSIGNED:
            work_item.queue_status = WorkQueueStatusEnum.PENDING_ASSIGNED
            released_work_ids.append(work_item.work_id)

    action = _log_agent_action(
        db, None, AgentActionStatusEnum.SUCCESS,
        f"Marked roster_id={roster_id} (employee_id={roster.employee_id}) as ABSENT (was {old_status}); "
        f"released unstarted work_ids={released_work_ids}"
    )
    db.commit()

    print(f"         [OK] roster_id={roster_id}: {old_status} -> ABSENT")

    return {
        "roster_id": roster_id,
        "employee_id": roster.employee_id,
        "old_status": old_status,
        "new_status": "ABSENT",
        "released_work_ids": released_work_ids,
        "agent_action_id": action.agent_action_id,
    }


# Run directly from terminal

if __name__ == "__main__":
    from app.database.connection import SessionLocal

    parser = argparse.ArgumentParser(
        description="Workforce Agent â€” Validate availability and get eligible employees.",
        usage="python -m app.services.workforce_agent <command> [options]",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # validate_worker
    p_validate = subparsers.add_parser("validate_worker", help="Validate a single employee")
    p_validate.add_argument("employee_id", type=int, help="Employee ID to validate")

    # get_available_workers
    p_available = subparsers.add_parser("get_available_workers", help="List available workers in a department")
    p_available.add_argument("department_id", type=int, help="Department ID")

    # get_worker_metrics
    p_metrics = subparsers.add_parser("get_worker_metrics", help="Get workload metrics for an employee")
    p_metrics.add_argument("employee_id", type=int, help="Employee ID")

    # get_candidate
    p_candidate = subparsers.add_parser("get_candidate", help="Get all eligible candidates for a department")
    p_candidate.add_argument("department_id", type=int, help="Department ID")

    # update_worker_task_metrics
    p_update_metrics = subparsers.add_parser("update_worker_task_metrics", help="Update WorkerMemory metrics for an employee")
    p_update_metrics.add_argument("employee_id", type=int, help="Employee ID")
    p_update_metrics.add_argument("new_status", type=str, help="New status (e.g. COMPLETED, CANCELLED)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        raise SystemExit(1)

    db = SessionLocal()

    try:
        if args.command == "validate_worker":
            validate_worker(args.employee_id, db)

        elif args.command == "get_available_workers":
            get_available_workers(args.department_id, db)

        elif args.command == "get_worker_metrics":
            get_worker_metrics(args.employee_id, db)

        elif args.command == "get_candidate":
            get_candidate(args.department_id, db)

        elif args.command == "update_worker_task_metrics":
            update_worker_task_metrics(args.employee_id, args.new_status, db)

    except ValueError as e:
        print(f"\nERROR: {e}")
    finally:
        db.close()
