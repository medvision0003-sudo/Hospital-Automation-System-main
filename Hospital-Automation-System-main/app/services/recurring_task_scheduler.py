"""
Recurring Task Scheduler — Service Layer
Generates DepartmentWorkQueue entries for schedules defined in TaskSchedule.
Does NOT perform task assignment — only creates PENDING work items.

Public Functions:
    compute_next_run()          — Calculate the next execution timestamp
    is_shift_active_now()       — Check if a shift window covers the current time
    next_shift_start_after()    — Compute the next future start datetime of a shift
    get_next_scheduler_wake()   — Earliest wake time considering shift gates
    generate_scheduled_tasks()  — Find due schedules and generate work items
    signal_scheduler_wake()     — Wake the background timer when schedules change
    start_scheduler()           — Launch the background timer thread
    stop_scheduler()            — Gracefully stop the background timer thread
"""

import threading
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session, joinedload

from app.models.task_master import TaskMaster
from app.models.task_schedule import TaskSchedule
from app.models.department_work_queue import DepartmentWorkQueue
from app.models.employee import Employee
from app.models.shift_roster import ShiftRoster
from app.models.worker_checkin import WorkerCheckin
from app.models.enums import (
    TaskStatusEnum,
    FrequencyTypeEnum,
    CheckinStatusEnum,
    RosterStatusEnum,
    HospitalEventEnum,
    WorkQueueStatusEnum,
)
from app.services.outbox_dispatcher import create_outbox_event, signal_outbox_wake
from app.agents.task_management_agent import create_work_item


_scheduler_wake_event = threading.Event()
_scheduler_stop_event = threading.Event()
_scheduler_thread = None


def compute_next_run(frequency_type, frequency_value, from_time=None):
    """
    Calculate the next execution timestamp based on frequency type and value.

    Args:
        frequency_type: FrequencyTypeEnum value (MINUTES, HOURS, DAYS, WEEKS, MONTHS)
        frequency_value: Integer interval (e.g. 4 for "every 4 hours")
        from_time: Base timestamp to compute from (defaults to now)

    Returns:
        datetime: The next scheduled execution time
    """
    base = from_time or datetime.now()

    if frequency_type == FrequencyTypeEnum.MINUTES:
        return base + timedelta(minutes=frequency_value)

    elif frequency_type == FrequencyTypeEnum.HOURS:
        return base + timedelta(hours=frequency_value)

    elif frequency_type == FrequencyTypeEnum.DAYS:
        return base + timedelta(days=frequency_value)

    elif frequency_type == FrequencyTypeEnum.WEEKS:
        return base + timedelta(weeks=frequency_value)

    elif frequency_type == FrequencyTypeEnum.MONTHS:
        return base + relativedelta(months=frequency_value)

    else:
        raise ValueError(f"Unknown frequency_type: {frequency_type}")


def is_shift_active_now(shift, now):
    """
    Check whether a shift window covers the given datetime.
    Pure function — no DB access.

    Normal shift (e.g. 07:00-15:00):
        active if start_time <= now.time() < end_time

    Overnight shift (e.g. 22:00-06:00):
        active if now.time() >= start_time OR now.time() < end_time

    This app does not model 24-hour recurring shift windows yet,
    so start_time == end_time raises ValueError.

    Args:
        shift: Object with start_time and end_time (datetime.time)
        now:   datetime to check against

    Returns:
        bool
    """
    if shift.start_time == shift.end_time:
        raise ValueError(
            "start_time == end_time is invalid; "
            "24-hour recurring shift windows are not supported"
        )

    current = now.time()

    if shift.start_time < shift.end_time:
        return shift.start_time <= current < shift.end_time
    else:
        return current >= shift.start_time or current < shift.end_time


def next_shift_start_after(shift, now):
    """
    Compute the next future start datetime of a shift, strictly greater than now.
    Pure function — no DB access.

    If today's start has already passed (or is exactly now), returns tomorrow's start.

    Args:
        shift: Object with start_time (datetime.time)
        now:   datetime reference point

    Returns:
        datetime strictly in the future
    """
    candidate = datetime.combine(now.date(), shift.start_time)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def _shift_end_datetime(shift, now):
    """Return the end of the shift window containing now."""
    start_time = shift.start_time
    end_time = shift.end_time
    if start_time < end_time:
        return datetime.combine(now.date(), end_time)
    if now.time() >= start_time:
        return datetime.combine(now.date() + timedelta(days=1), end_time)
    return datetime.combine(now.date(), end_time)


def _task_due_date(task, shift, now):
    """Use a template due time, then shift end, then estimated duration."""
    if task.due_time:
        due_date = datetime.combine(now.date(), task.due_time)
        if (
            shift
            and shift.start_time > shift.end_time
            and task.due_time <= shift.end_time
            and now.time() >= shift.start_time
        ):
            due_date += timedelta(days=1)
        return due_date
    if shift and is_shift_active_now(shift, now):
        return _shift_end_datetime(shift, now)
    minutes = task.estimated_time or 60
    return now + timedelta(minutes=minutes)


def _has_checked_in_worker(db, department_id, shift_id, now):
    """Check whether an employee is eligible for immediate assignment."""
    if department_id is None:
        return False

    roster_statuses = (
        RosterStatusEnum.CHECKED_IN,
        RosterStatusEnum.HALF_DAY,
        RosterStatusEnum.OVERTIME,
    )
    rows = (
        db.query(ShiftRoster, WorkerCheckin)
        .join(Employee, Employee.employee_id == ShiftRoster.employee_id)
        .join(WorkerCheckin, WorkerCheckin.employee_id == Employee.employee_id)
        .filter(
            Employee.department_id == department_id,
            ShiftRoster.roster_status.in_(roster_statuses),
            WorkerCheckin.status == CheckinStatusEnum.CHECKED_IN,
            WorkerCheckin.checkout_time.is_(None),
            WorkerCheckin.checkin_time <= now,
        )
        .all()
    )

    for roster, checkin in rows:
        if shift_id is not None and roster.shift_id != shift_id:
            continue
        start = datetime.combine(roster.work_date, roster.shift.start_time)
        end = datetime.combine(roster.work_date, roster.shift.end_time)
        if end <= start:
            end += timedelta(days=1)
        if roster.roster_status == RosterStatusEnum.OVERTIME and roster.overtime_end_time:
            end = max(end, roster.overtime_end_time)
        if start <= now < end:
            return True
    return False


def _has_current_roster(db, department_id, shift_id, now):
    """Keep due work visible when a scheduled shift has no present employee."""
    if department_id is None:
        return False

    roster_statuses = (
        RosterStatusEnum.SCHEDULED,
        RosterStatusEnum.CHECKED_IN,
        RosterStatusEnum.HALF_DAY,
        RosterStatusEnum.ABSENT,
        RosterStatusEnum.OVERTIME,
    )
    rosters = (
        db.query(ShiftRoster)
        .join(Employee, Employee.employee_id == ShiftRoster.employee_id)
        .filter(
            Employee.department_id == department_id,
            ShiftRoster.roster_status.in_(roster_statuses),
        )
        .all()
    )
    for roster in rosters:
        if shift_id is not None and roster.shift_id != shift_id:
            continue
        start = datetime.combine(roster.work_date, roster.shift.start_time)
        end = datetime.combine(roster.work_date, roster.shift.end_time)
        if end <= start:
            end += timedelta(days=1)
        if roster.roster_status == RosterStatusEnum.OVERTIME and roster.overtime_end_time:
            end = max(end, roster.overtime_end_time)
        if start <= now < end:
            return True
    return False


def _has_open_work_item(db, task_id, department_id, shift_id):
    """Prevent a recurring schedule from creating duplicate unfinished work."""
    task_lock = db.query(TaskMaster).filter(TaskMaster.task_id == task_id)
    if db.bind.dialect.name == "postgresql":
        task_lock = task_lock.with_for_update()
    task_lock.first()

    query = db.query(DepartmentWorkQueue).filter(
        DepartmentWorkQueue.task_id == task_id,
        DepartmentWorkQueue.department_id == department_id,
        DepartmentWorkQueue.queue_status.in_(
            (
                WorkQueueStatusEnum.PENDING_ASSIGNED,
                WorkQueueStatusEnum.ASSIGNED,
            )
        ),
    )
    if shift_id is None:
        query = query.filter(DepartmentWorkQueue.shift_id.is_(None))
    else:
        query = query.filter(DepartmentWorkQueue.shift_id == shift_id)
    return query.first() is not None


def _has_work_item_today(db, task_id, department_id, shift_id, now):
    """Prevent check-in task generation from duplicating today's work."""
    day_start = datetime.combine(now.date(), datetime.min.time())
    day_end = day_start + timedelta(days=1)
    query = db.query(DepartmentWorkQueue).filter(
        DepartmentWorkQueue.task_id == task_id,
        DepartmentWorkQueue.department_id == department_id,
        DepartmentWorkQueue.created_at >= day_start,
        DepartmentWorkQueue.created_at < day_end,
    )
    if shift_id is None:
        query = query.filter(DepartmentWorkQueue.shift_id.is_(None))
    else:
        query = query.filter(DepartmentWorkQueue.shift_id == shift_id)
    return query.first() is not None


def get_next_scheduler_wake(db, now):
    """
    Compute the earliest datetime the scheduler should wake up.

    Considers two sources:
      1. The nearest future next_run among all active schedules.
      2. The nearest shift-start for any due-but-inactive shift-gated schedule
         (next_run <= now, but the shift is not currently active).

    Args:
        db:  SQLAlchemy Session
        now: datetime reference point

    Returns:
        datetime or None if there is nothing to wake for
    """
    candidates = []

    nearest_future = (
        db.query(TaskSchedule)
        .join(TaskMaster, TaskSchedule.task_id == TaskMaster.task_id)
        .filter(
            TaskSchedule.is_active == True,
            TaskMaster.task_state == TaskStatusEnum.ACTIVE,
            TaskSchedule.next_run > now,
            TaskSchedule.next_run.isnot(None),
        )
        .order_by(TaskSchedule.next_run.asc())
        .first()
    )
    if nearest_future:
        candidates.append(nearest_future.next_run)

    due_gated = (
        db.query(TaskSchedule)
        .join(TaskMaster, TaskSchedule.task_id == TaskMaster.task_id)
        .options(joinedload(TaskSchedule.shift))
        .filter(
            TaskSchedule.is_active == True,
            TaskMaster.task_state == TaskStatusEnum.ACTIVE,
            TaskSchedule.next_run <= now,
            TaskSchedule.next_run.isnot(None),
            TaskSchedule.shift_id.isnot(None),
        )
        .all()
    )
    for sched in due_gated:
        if sched.shift and not is_shift_active_now(sched.shift, now):
            candidates.append(next_shift_start_after(sched.shift, now))

    return min(candidates) if candidates else None


def generate_scheduled_tasks(
    db: Session,
    *,
    department_id=None,
    shift_id=None,
    current_time=None,
    dispatch_events=True,
    include_future=False,
    workflow_id=None,
):
    """
    Generate DepartmentWorkQueue entries for due active schedules. Check-in
    workflows can set include_future to materialize the active shift's full
    task set rather than waiting for each suggested start time.

    For each due schedule:
        1. If the schedule is shift-gated, check if the shift is active now.
           If inactive, skip generation without mutating next_run.
        2. Create a DepartmentWorkQueue entry (PENDING_ASSIGNED)
        3. Log an event via Event Agent (RECURRING_TASK_GENERATED)
        4. Update last_run and next_run on the TaskSchedule row
           (TaskMaster is NEVER written to by the scheduler)

    Args:
        db: SQLAlchemy Session

    Returns:
        dict with generated_count and list of generated task details
    """
    now = current_time or datetime.now()
    if isinstance(now, str):
        now = datetime.fromisoformat(now.replace("Z", "+00:00"))
    if now.tzinfo is not None:
        now = now.astimezone().replace(tzinfo=None)

    print("=" * 60)
    print("  RECURRING TASK SCHEDULER -- Starting")
    print("=" * 60)

    schedule_filter = "active schedules" if include_future else f"due schedules (next_run <= {now})"
    print(f"\n[Step 1] Querying {schedule_filter}...")

    due_query = (
        db.query(TaskSchedule)
        .join(TaskMaster, TaskSchedule.task_id == TaskMaster.task_id)
        .options(
            joinedload(TaskSchedule.task),
            joinedload(TaskSchedule.shift),
        )
        .filter(
            TaskSchedule.is_active == True,
            TaskMaster.task_state == TaskStatusEnum.ACTIVE,
            TaskSchedule.next_run.isnot(None),
        )
        .order_by(TaskSchedule.next_run.asc())
    )
    if not include_future:
        due_query = due_query.filter(TaskSchedule.next_run <= now)
    if department_id is not None:
        due_query = due_query.filter(TaskMaster.department_id == department_id)
    if shift_id is not None:
        due_query = due_query.filter(
            (TaskSchedule.shift_id == shift_id) | TaskSchedule.shift_id.is_(None)
        )
    elif department_id is not None:
        due_query = due_query.filter(TaskSchedule.shift_id.is_(None))
    if db.bind.dialect.name == "postgresql":
        due_query = due_query.with_for_update(of=TaskSchedule)
    due_schedules = due_query.all()

    if not due_schedules:
        print("         No schedules are due right now.")
        print("=" * 60)
        return {"generated_count": 0, "tasks": [], "failures": []}

    schedule_label = "active" if include_future else "due"
    print(f"         Found {len(due_schedules)} {schedule_label} schedule(s)")

    generated = []
    failures = []
    skipped = []

    for schedule in due_schedules:
        task = schedule.task
        print(
            f"\n[Step 2] Processing schedule '{schedule.schedule_name}' "
            f"for task '{task.task_name}' (task_id={task.task_id})"
        )

        # Shift gatekeeper: skip if shift is set but not currently active
        if schedule.shift:
            try:
                if not is_shift_active_now(schedule.shift, now):
                    print(
                        f"         SKIPPED: shift '{schedule.shift.shift_name}' "
                        f"is not active at {now.time()}"
                    )
                    continue
            except ValueError as ve:
                print(f"         SKIPPED: shift configuration error: {ve}")
                continue

        eligible_shift_id = schedule.shift_id or shift_id
        if not _has_current_roster(db, task.department_id, eligible_shift_id, now):
            print("         SKIPPED: no active roster in the task's department and shift")
            continue

        try:
            eligible_shift_id = schedule.shift_id or shift_id
            if _has_open_work_item(
                db,
                task.task_id,
                task.department_id,
                eligible_shift_id,
            ):
                old_next_run = schedule.next_run
                schedule.last_run = now
                schedule.next_run = compute_next_run(
                    schedule.frequency_type,
                    schedule.frequency_value,
                    max(old_next_run, now) if include_future else now,
                )
                db.commit()
                skipped.append({
                    "schedule_id": schedule.schedule_id,
                    "task_id": task.task_id,
                    "shift_id": eligible_shift_id,
                    "reason": "unfinished work already exists for this task and shift",
                    "next_run": str(schedule.next_run),
                })
                print(
                    f"         SKIPPED: unfinished work already exists; "
                    f"next_run advanced from {old_next_run} to {schedule.next_run}"
                )
                continue

            if include_future and _has_work_item_today(
                db,
                task.task_id,
                task.department_id,
                eligible_shift_id,
                now,
            ):
                if schedule.next_run <= now:
                    schedule.next_run = compute_next_run(
                        schedule.frequency_type,
                        schedule.frequency_value,
                        now,
                    )
                    db.commit()
                skipped.append({
                    "schedule_id": schedule.schedule_id,
                    "task_id": task.task_id,
                    "shift_id": eligible_shift_id,
                    "reason": "work already exists for this task and shift today",
                    "next_run": str(schedule.next_run),
                })
                continue

            dispatch_assignment = dispatch_events and _has_checked_in_worker(
                db, task.department_id, eligible_shift_id, now
            )
            work_result = create_work_item(
                task_id=task.task_id,
                due_date=_task_due_date(task, schedule.shift, now),
                db=db,
                commit=False,
                shift_id=schedule.shift_id or shift_id,
                workflow_id=workflow_id,
            )
            work_item = (
                db.query(DepartmentWorkQueue)
                .filter(DepartmentWorkQueue.work_id == work_result["work_id"])
                .first()
            )
            event_id = work_result["event_id"]
            print(f"         Created work_id={work_item.work_id}")

            # Capture old_next_run before mutation for dedupe key
            old_next_run = schedule.next_run

            # Create outbox event in same transaction as the work item
            if dispatch_assignment:
                create_outbox_event(
                    db=db,
                    event_type=HospitalEventEnum.RECURRING_TASK_GENERATED.value,
                    payload={"work_id": work_item.work_id},
                    dedupe_key=f"RECURRING_TASK_GENERATED:schedule_id={schedule.schedule_id}:run_at={old_next_run.isoformat()}",
                )

            schedule.last_run = now
            schedule.next_run = compute_next_run(
                schedule.frequency_type,
                schedule.frequency_value,
                max(old_next_run, now) if include_future else now,
            )

            print(f"         Updated next_run: {old_next_run} -> {schedule.next_run}")

            db.commit()

            # Wake outbox after commit so dispatcher picks up the event
            if dispatch_assignment:
                signal_outbox_wake()

            generated.append({
                "schedule_id": schedule.schedule_id,
                "schedule_name": schedule.schedule_name,
                "task_id": task.task_id,
                "task_name": task.task_name,
                "work_id": work_item.work_id,
                "event_id": event_id,
                "agent_action_id": work_result["agent_action_id"],
                "next_run": str(schedule.next_run),
                "due_date": str(work_item.due_date),
                "shift_id": work_item.shift_id,
            })

            print(f"         Committed successfully")

        except Exception as e:
            db.rollback()
            print(f"         ERROR processing schedule_id={schedule.schedule_id}: {e}")
            failures.append({
                "schedule_id": schedule.schedule_id,
                "reason": str(e),
            })

    result = {
        "generated_count": len(generated),
        "tasks": generated,
        "failures": failures,
        "skipped_count": len(skipped),
        "skipped": skipped,
    }

    print(f"\n[Step 3] Generation complete!")
    print()
    print("=" * 60)
    print("  RESULT")
    print("=" * 60)
    print(f"  generated_count    : {result['generated_count']}")
    for t in result["tasks"]:
        print(
            f"  schedule={t['schedule_name']} task_id={t['task_id']} "
            f"({t['task_name']}) -> work_id={t['work_id']}, next_run={t['next_run']}"
        )
    print("=" * 60)

    return result


def signal_scheduler_wake():
    """
    Wake the background scheduler timer so it recalculates the nearest next_run.
    Called by API routes when a schedule is created or updated.
    """
    print("[SCHEDULER] Wake signal received -- recalculating schedule")
    _scheduler_wake_event.set()


def _scheduler_loop():
    """
    Internal background loop that runs in a daemon thread.

    1. Generate any overdue tasks (catch-up), respecting shift gates
    2. Compute the next wake time via get_next_scheduler_wake
    3. Sleep until that time (or until a wake signal interrupts)
    4. Repeat
    """
    from app.database.connection import SessionLocal

    print("[SCHEDULER] Background timer started")

    while not _scheduler_stop_event.is_set():
        db = SessionLocal()

        try:
            generate_scheduled_tasks(db)

            now = datetime.now()
            wake_at = get_next_scheduler_wake(db, now)

            if wake_at:
                sleep_seconds = max((wake_at - now).total_seconds(), 1)
                print(
                    f"[SCHEDULER] Next wake at {wake_at} "
                    f"(sleeping {sleep_seconds:.0f}s)"
                )
            else:
                sleep_seconds = None
                print("[SCHEDULER] No future schedules -- sleeping until wake signal")

        except Exception as e:
            print(f"[SCHEDULER] Error in scheduler loop: {e}")
            sleep_seconds = 60

        finally:
            db.close()

        _scheduler_wake_event.clear()

        if sleep_seconds is not None:
            _scheduler_wake_event.wait(timeout=sleep_seconds)
        else:
            _scheduler_wake_event.wait()

        if _scheduler_stop_event.is_set():
            break

        print("[SCHEDULER] Woke up -- recalculating schedule")

    print("[SCHEDULER] Background timer stopped")


def start_scheduler():
    """Launch the background scheduler timer thread (idempotent)."""
    global _scheduler_thread

    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        print("[SCHEDULER] Scheduler already running, skipping start")
        return

    _scheduler_stop_event.clear()
    _scheduler_wake_event.clear()

    _scheduler_thread = threading.Thread(
        target=_scheduler_loop,
        name="RecurringTaskScheduler",
        daemon=True,
    )
    _scheduler_thread.start()
    print("[SCHEDULER] Scheduler started")


def stop_scheduler():
    """Gracefully stop the background scheduler timer thread."""
    global _scheduler_thread

    print("[SCHEDULER] Stopping scheduler...")
    _scheduler_stop_event.set()
    _scheduler_wake_event.set()

    if _scheduler_thread and _scheduler_thread.is_alive():
        _scheduler_thread.join(timeout=5)

    _scheduler_thread = None
    print("[SCHEDULER] Scheduler stopped")


if __name__ == "__main__":
    from app.database.connection import SessionLocal

    print("Running one-shot scheduled task generation...\n")
    db = SessionLocal()

    try:
        result = generate_scheduled_tasks(db)
        print(f"\nGenerated {result['generated_count']} work item(s)")
    except Exception as e:
        print(f"\nERROR: {e}")
    finally:
        db.close()
