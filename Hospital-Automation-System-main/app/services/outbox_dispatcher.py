"""
Outbox Dispatcher -- Background Service

Manages the transactional outbox event bus and autonomous state watchers.
Runs a background daemon thread that:
  1. Recovers stuck PROCESSING events.
  2. Runs autonomous watchers to detect system anomalies.
  3. Processes pending outbox events by forwarding them through the Event Agent.

Public Functions:
    create_outbox_event()       -- Insert an outbox event (caller owns commit).
    process_pending_outbox_events() -- Poll and process a batch of pending events.
    signal_outbox_wake()        -- Wake the poller for immediate processing.
    start_outbox_service()      -- Launch the background daemon thread (idempotent).
    stop_outbox_service()       -- Gracefully stop the daemon thread.
"""

import json
import threading
import uuid
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.outbox_event import OutboxEvent
from app.models.department_work_queue import DepartmentWorkQueue
from app.models.worker_memory import WorkerMemory
from app.models.shift_roster import ShiftRoster
from app.models.shift import Shift
from app.models.agent_action_log import AgentActionLog
from app.models.enums import (
    HospitalEventEnum,
    WorkQueueStatusEnum,
    RosterStatusEnum,
)
from app.services.system_config_service import get_config_value


# Watcher threshold constants (static fallbacks only for MAX_ATTEMPTS)
MAX_ATTEMPTS = 3

# Thread synchronization
_outbox_wake_event = threading.Event()
_outbox_stop_event = threading.Event()
_outbox_thread = None


# Core Functions

def create_outbox_event(
    db: Session,
    event_type: str,
    payload: dict,
    dedupe_key: str = None,
    available_after: datetime = None,
) -> OutboxEvent:
    """Insert an outbox event record. Does NOT commit.

    The caller owns the transaction and must call db.commit() to persist
    both the business data and the outbox event atomically.

    After flushing, the database unique index on dedupe_key may raise
    an IntegrityError. The caller (e.g. a watcher) should catch this
    using db.begin_nested() to roll back only the duplicate insert.

    Args:
        db:              SQLAlchemy session (caller-owned).
        event_type:      String value from HospitalEventEnum.
        payload:         Dict of event-specific data (serialized to JSON).
        dedupe_key:      Optional unique string to prevent duplicate events.
        available_after: Optional timestamp for delayed processing.

    Returns:
        The created OutboxEvent instance (not yet committed).
    """
    event = OutboxEvent(
        event_id=str(uuid.uuid4()),
        event_type=event_type,
        payload_json=json.dumps(payload, default=str),
        dedupe_key=dedupe_key,
        status="PENDING",
        available_after=available_after,
    )
    db.add(event)
    db.flush()

    print(f"[OUTBOX] Created event: {event_type} (id={event.event_id})")
    return event


def process_pending_outbox_events(db: Session) -> int:
    """Process a batch of pending outbox events.

    Sequence:
      1. Recover stuck PROCESSING events older than STUCK_PROCESSING_MINUTES.
      2. Select up to BATCH_LIMIT events in PENDING or retryable FAILED state.
      3. Mark them PROCESSING and commit immediately.
      4. Execute each via Event Agent publish_event.
      5. Mark COMPLETED on success, FAILED/DEAD on failure, and commit.

    Returns:
        Number of events processed in this cycle.
    """
    from app.agents.event_agent import publish_event

    now = datetime.now()

    # Step 1: Recover stuck PROCESSING events
    stuck_processing_minutes = get_config_value(db, "STUCK_PROCESSING_MINUTES", 5)
    stuck_cutoff = now - timedelta(minutes=stuck_processing_minutes)
    stuck_events = (
        db.query(OutboxEvent)
        .filter(
            OutboxEvent.status == "PROCESSING",
            OutboxEvent.processing_started_at < stuck_cutoff,
        )
        .all()
    )
    for event in stuck_events:
        event.attempts += 1
        if event.attempts >= MAX_ATTEMPTS:
            event.status = "DEAD"
            event.last_error = "Stuck in PROCESSING, max attempts exceeded"
            print(f"[OUTBOX] Stuck event {event.event_id} moved to DEAD (attempts={event.attempts})")
        else:
            event.status = "PENDING"
            event.processing_started_at = None
            print(f"[OUTBOX] Stuck event {event.event_id} reset to PENDING (attempts={event.attempts})")
    if stuck_events:
        db.commit()

    # Step 2: Select batch of PENDING or retryable FAILED events
    batch = (
        db.query(OutboxEvent)
        .filter(
            OutboxEvent.status.in_(["PENDING", "FAILED"]),
            OutboxEvent.attempts < MAX_ATTEMPTS,
            (OutboxEvent.available_after <= now) | (OutboxEvent.available_after.is_(None)),
        )
        .order_by(OutboxEvent.created_at.asc())
        .limit(get_config_value(db, "OUTBOX_BATCH_LIMIT", 20))
        .all()
    )

    if not batch:
        return 0

    # Step 3: Mark batch as PROCESSING
    for event in batch:
        event.status = "PROCESSING"
        event.processing_started_at = now
    db.commit()

    # Step 4: Process each event
    processed = 0
    for event in batch:
        try:
            payload = json.loads(event.payload_json)
            event_enum = HospitalEventEnum(event.event_type)

            print(f"[OUTBOX] Processing event {event.event_id} ({event.event_type})...")
            publish_event(event_enum, payload, db)

            # Step 5a: Mark COMPLETED
            event.status = "COMPLETED"
            event.processed_at = datetime.now()
            db.commit()
            processed += 1
            print(f"[OUTBOX] Event {event.event_id} COMPLETED")

        except Exception as exc:
            db.rollback()
            # Re-fetch the event after rollback to avoid detached instance
            event = db.query(OutboxEvent).filter(OutboxEvent.event_id == event.event_id).first()
            if not event:
                continue

            event.attempts += 1
            event.last_error = str(exc)[:500]
            event.processing_started_at = None

            if event.attempts >= MAX_ATTEMPTS:
                event.status = "DEAD"
                print(f"[OUTBOX] Event {event.event_id} DEAD after {event.attempts} attempts: {exc}")
            else:
                event.status = "FAILED"
                # Back off: delay retry by 30 seconds per attempt
                event.available_after = datetime.now() + timedelta(seconds=30 * event.attempts)
                print(f"[OUTBOX] Event {event.event_id} FAILED (attempt {event.attempts}): {exc}")

            db.commit()

    return processed


# Autonomous State Watchers

def run_timeout_watcher(db: Session):
    """Detect assigned tasks past their due date.

    Creates TASK_TIMEOUT_DETECTED events for work items in ASSIGNED
    status where due_date < now().
    """
    now = datetime.now()
    overdue_items = (
        db.query(DepartmentWorkQueue)
        .filter(
            DepartmentWorkQueue.queue_status == WorkQueueStatusEnum.ASSIGNED,
            DepartmentWorkQueue.due_date < now,
            DepartmentWorkQueue.due_date.isnot(None),
        )
        .all()
    )

    for item in overdue_items:
        dedupe_key = f"TASK_TIMEOUT_DETECTED:work_id={item.work_id}"
        try:
            nested = db.begin_nested()
            create_outbox_event(
                db=db,
                event_type=HospitalEventEnum.TASK_TIMEOUT_DETECTED.value,
                payload={"work_id": item.work_id},
                dedupe_key=dedupe_key,
            )
            nested.commit()
        except Exception:
            db.rollback()
            print(f"[WATCHER] Skipped duplicate: {dedupe_key}")

    db.commit()


def run_staff_shortage_watcher(db: Session):
    """Detect tasks stuck in PENDING_ASSIGNED for too long.

    Creates STAFF_SHORTAGE_DETECTED events for work items that have been
    waiting for assignment longer than STAFF_SHORTAGE_MINUTES.
    """
    cutoff = datetime.now() - timedelta(minutes=get_config_value(db, "STAFF_SHORTAGE_MINUTES", 5))
    stale_items = (
        db.query(DepartmentWorkQueue)
        .filter(
            DepartmentWorkQueue.queue_status == WorkQueueStatusEnum.PENDING_ASSIGNED,
            DepartmentWorkQueue.created_at < cutoff,
        )
        .all()
    )

    from app.models.employee import Employee

    for item in stale_items:
        # Check if there is any active roster for this department on the current date
        # (roster_status in CHECKED_IN, HALF_DAY, OVERTIME)
        active_roster_exists = (
            db.query(ShiftRoster)
            .join(Employee)
            .filter(
                Employee.department_id == item.department_id,
                ShiftRoster.work_date == datetime.now().date(),
                ShiftRoster.roster_status.in_([
                    RosterStatusEnum.CHECKED_IN,
                    RosterStatusEnum.HALF_DAY,
                    RosterStatusEnum.OVERTIME,
                ])
            )
            .first()
        ) is not None

        if not active_roster_exists:
            # Skip triggering staff shortage if there are no active/online workers in the department
            continue

        dedupe_key = f"STAFF_SHORTAGE_DETECTED:work_id={item.work_id}"
        try:
            nested = db.begin_nested()
            create_outbox_event(
                db=db,
                event_type=HospitalEventEnum.STAFF_SHORTAGE_DETECTED.value,
                payload={"work_id": item.work_id},
                dedupe_key=dedupe_key,
            )
            nested.commit()
        except Exception:
            db.rollback()
            print(f"[WATCHER] Skipped duplicate: {dedupe_key}")

    db.commit()


def run_workload_watcher(db: Session):
    """Detect overloaded workers using dynamic average-based thresholds.

    Computes the average pending_task count across all checked-in workers
    (roster status CHECKED_IN or HALF_DAY for today). A worker is flagged as
    overloaded when their pending tasks exceed the average by
    OVERLOAD_ABOVE_AVG_THRESHOLD.

    Creates WORKER_OVERLOAD_DETECTED events with hourly deduplication.
    """
    from datetime import date
    from sqlalchemy import func as sa_func

    today = date.today()

    # Get employee_ids of all workers checked in today
    checked_in_ids = (
        db.query(ShiftRoster.employee_id)
        .filter(
            ShiftRoster.work_date == today,
            ShiftRoster.roster_status.in_([
                RosterStatusEnum.CHECKED_IN,
                RosterStatusEnum.HALF_DAY,
            ]),
        )
        .distinct()
        .all()
    )
    checked_in_employee_ids = [row[0] for row in checked_in_ids]

    if not checked_in_employee_ids:
        return

    # Get WorkerMemory rows for all checked-in workers
    active_memories = (
        db.query(WorkerMemory)
        .filter(WorkerMemory.employee_id.in_(checked_in_employee_ids))
        .all()
    )

    if not active_memories:
        return

    # Compute average pending tasks across all checked-in workers
    total_pending = sum((m.pending_task or 0) for m in active_memories)
    avg_pending = total_pending / len(active_memories)
    dynamic_limit = avg_pending + get_config_value(db, "OVERLOAD_ABOVE_AVG_THRESHOLD", 3)

    # Flag workers exceeding the dynamic threshold
    overloaded = [m for m in active_memories if (m.pending_task or 0) >= dynamic_limit]

    hour_stamp = datetime.now().strftime("%Y-%m-%dT%H")
    for memory in overloaded:
        dedupe_key = f"WORKER_OVERLOAD_DETECTED:employee_id={memory.employee_id}:hour={hour_stamp}"
        try:
            nested = db.begin_nested()
            create_outbox_event(
                db=db,
                event_type=HospitalEventEnum.WORKER_OVERLOAD_DETECTED.value,
                payload={
                    "employee_id": memory.employee_id,
                    "pending_tasks": memory.pending_task,
                    "avg_pending": round(avg_pending, 2),
                    "threshold": round(dynamic_limit, 2),
                },
                dedupe_key=dedupe_key,
            )
            nested.commit()
        except Exception:
            db.rollback()
            print(f"[WATCHER] Skipped duplicate: {dedupe_key}")

    db.commit()


def run_shift_transition_watcher(db: Session):
    """Detect shifts that have ended but roster entries are still active.

    Computes full shift end datetimes using roster work_date and shift times
    to correctly handle overnight shifts. Creates SHIFT_CHANGE_DETECTED events
    for rosters where the shift end has passed but roster_status is still active.

    For overnight shifts, filters using work_date >= today - 1 day.
    For OVERTIME rosters, respects overtime_end_time before emitting events.
    """
    now = datetime.now()
    today = now.date()
    yesterday = today - timedelta(days=1)

    stale_rosters = (
        db.query(ShiftRoster)
        .join(Shift, ShiftRoster.shift_id == Shift.shift_id)
        .filter(
            ShiftRoster.work_date >= yesterday,
            ShiftRoster.roster_status.in_([
                RosterStatusEnum.SCHEDULED,
                RosterStatusEnum.CHECKED_IN,
                RosterStatusEnum.HALF_DAY,
                RosterStatusEnum.OVERTIME,
            ]),
        )
        .all()
    )

    for roster in stale_rosters:
        shift = db.query(Shift).filter(Shift.shift_id == roster.shift_id).first()
        if not shift:
            continue

        # Build full datetime for shift end
        shift_start_dt = datetime.combine(roster.work_date, shift.start_time)
        shift_end_dt = datetime.combine(roster.work_date, shift.end_time)
        # Handle overnight shifts: if end_time <= start_time, shift spans midnight
        if shift_end_dt <= shift_start_dt:
            shift_end_dt += timedelta(days=1)

        # For overtime rosters, use overtime_end_time instead of shift end
        effective_end = shift_end_dt
        if roster.roster_status == RosterStatusEnum.OVERTIME and roster.overtime_end_time:
            effective_end = roster.overtime_end_time

        if now <= effective_end:
            continue

        dedupe_key = f"SHIFT_CHANGE_DETECTED:roster_id={roster.roster_id}"
        try:
            nested = db.begin_nested()
            create_outbox_event(
                db=db,
                event_type=HospitalEventEnum.SHIFT_CHANGE_DETECTED.value,
                payload={"roster_id": roster.roster_id},
                dedupe_key=dedupe_key,
            )
            nested.commit()
        except Exception:
            db.rollback()
            print(f"[WATCHER] Skipped duplicate: {dedupe_key}")

    db.commit()


def run_shift_start_watcher(db: Session):
    """Trigger assignment reevaluation when a rostered shift is active."""
    now = datetime.now()
    today = now.date()
    yesterday = today - timedelta(days=1)
    rosters = (
        db.query(ShiftRoster)
        .join(Shift, ShiftRoster.shift_id == Shift.shift_id)
        .filter(
            ShiftRoster.work_date >= yesterday,
            ShiftRoster.work_date <= today,
            ShiftRoster.roster_status.in_([
                RosterStatusEnum.SCHEDULED,
                RosterStatusEnum.CHECKED_IN,
                RosterStatusEnum.HALF_DAY,
            ]),
        )
        .all()
    )

    for roster in rosters:
        shift = db.query(Shift).filter(Shift.shift_id == roster.shift_id).first()
        if not shift:
            continue

        start = datetime.combine(roster.work_date, shift.start_time)
        end = datetime.combine(roster.work_date, shift.end_time)
        if end <= start:
            end += timedelta(days=1)
        if not start <= now < end:
            continue

        dedupe_key = f"SHIFT_STARTED:roster_id={roster.roster_id}"
        nested = db.begin_nested()
        try:
            create_outbox_event(
                db=db,
                event_type=HospitalEventEnum.SHIFT_STARTED.value,
                payload={"roster_id": roster.roster_id},
                dedupe_key=dedupe_key,
            )
            nested.commit()
        except IntegrityError:
            nested.rollback()
            print(f"[WATCHER] Skipped duplicate: {dedupe_key}")

    db.commit()


def run_approval_timeout_watcher(db: Session):
    """Auto-resolve SHIFT_HANDOVER_REVIEW approvals older than 15 minutes.

    When a handover approval times out, automatically executes Choice B:
    preempts ASSIGNED tasks (marks as PREEMPTED), reverts work items to
    PENDING_ASSIGNED, completes the roster, and triggers a reassignment cycle.
    """
    import json
    from app.models.approval_request import ApprovalRequest

    timeout_cutoff = datetime.now() - timedelta(minutes=get_config_value(db, "HANDOVER_REVIEW_TIMEOUT_MINUTES", 15))

    timed_out = (
        db.query(ApprovalRequest)
        .filter(
            ApprovalRequest.sensitive_action == "SHIFT_HANDOVER_REVIEW",
            ApprovalRequest.status == "PENDING",
            ApprovalRequest.created_at < timeout_cutoff,
        )
        .all()
    )

    for approval in timed_out:
        print(f"[WATCHER] Auto-resolving timed-out SHIFT_HANDOVER_REVIEW approval_id={approval.approval_id}")
        try:
            from app.services.supervisor import resolve_shift_handover_choice_b
            resolve_shift_handover_choice_b(approval.approval_id, db)
            print(f"[WATCHER] Auto-resolved approval_id={approval.approval_id} via Choice B")
        except Exception as exc:
            print(f"[WATCHER] Failed to auto-resolve approval_id={approval.approval_id}: {exc}")
            db.rollback()

    db.commit()


def run_absentee_watcher(db: Session, current_time: datetime | None = None):
    """Detect workers who have not checked in within 30 minutes of shift start.

    Finds all today's rosters still in SCHEDULED state and computes whether
    the shift start plus 30-minute grace period has passed. Creates
    STAFF_ABSENT_DETECTED events for qualifying rosters.
    """
    from datetime import date

    now = current_time or datetime.now()
    today = now.date()

    scheduled_rosters = (
        db.query(ShiftRoster)
        .join(Shift, ShiftRoster.shift_id == Shift.shift_id)
        .filter(
            ShiftRoster.work_date.between(today - timedelta(days=1), today),
            ShiftRoster.roster_status == RosterStatusEnum.SCHEDULED,
        )
        .all()
    )

    for roster in scheduled_rosters:
        shift = db.query(Shift).filter(Shift.shift_id == roster.shift_id).first()
        if not shift:
            continue

        shift_start_dt = datetime.combine(roster.work_date, shift.start_time)
        shift_end_dt = datetime.combine(roster.work_date, shift.end_time)
        if shift_end_dt <= shift_start_dt:
            shift_end_dt += timedelta(days=1)
        if roster.roster_status == RosterStatusEnum.OVERTIME and roster.overtime_end_time:
            shift_end_dt = max(shift_end_dt, roster.overtime_end_time)

        absentee_timeout = get_config_value(db, "ABSENTEE_CHECKIN_TIMEOUT_MINUTES", 30)
        grace_cutoff = shift_start_dt + timedelta(minutes=absentee_timeout)

        if now <= grace_cutoff or now >= shift_end_dt:
            continue

        # Check if a recent snooze is active for this roster
        snooze_mins = get_config_value(db, "ABSENTEE_SNOOZE_MINUTES", 20)
        recent_snooze = (
            db.query(AgentActionLog)
            .filter(
                AgentActionLog.action_type == "SNOOZE_ABSENTEE",
                AgentActionLog.decision_summary.like(f"SNOOZE_ABSENTEE roster_id={roster.roster_id} %"),
                AgentActionLog.action_timestamp > now - timedelta(minutes=snooze_mins),
            )
            .first()
        )
        if recent_snooze:
            print(f"[WATCHER] Skipping roster_id={roster.roster_id} due to active {snooze_mins}-min snooze")
            continue

        dedupe_key = f"STAFF_ABSENT_DETECTED:roster_id={roster.roster_id}"
        nested = db.begin_nested()
        try:
            create_outbox_event(
                db=db,
                event_type=HospitalEventEnum.STAFF_ABSENT_DETECTED.value,
                payload={"roster_id": roster.roster_id},
                dedupe_key=dedupe_key,
            )
            nested.commit()
        except IntegrityError:
            nested.rollback()
            print(f"[WATCHER] Skipped duplicate: {dedupe_key}")

    db.commit()


# Background Daemon

def _outbox_loop():
    """Internal background loop that runs in a daemon thread.

    Each cycle:
      1. Run all autonomous watchers (produce events).
      2. Process pending outbox events (consume events).
      3. Sleep until next cycle or wake signal.
    """
    from app.database.connection import SessionLocal

    print("[OUTBOX] Background service started")

    while not _outbox_stop_event.is_set():
        db = SessionLocal()

        try:
            # Run watchers
            run_timeout_watcher(db)
            run_staff_shortage_watcher(db)
            run_workload_watcher(db)
            run_shift_transition_watcher(db)
            run_shift_start_watcher(db)
            run_approval_timeout_watcher(db)
            run_absentee_watcher(db)

            # Process outbox events
            processed = process_pending_outbox_events(db)
            if processed > 0:
                print(f"[OUTBOX] Processed {processed} event(s) this cycle")

            # Read poll interval while session is still open
            poll_interval = get_config_value(db, "OUTBOX_POLL_INTERVAL_SECONDS", 30)

        except Exception as e:
            poll_interval = 30
            print(f"[OUTBOX] Error in outbox loop: {e}")

        finally:
            db.close()

        _outbox_wake_event.clear()
        _outbox_wake_event.wait(timeout=poll_interval)

        if _outbox_stop_event.is_set():
            break

    print("[OUTBOX] Background service stopped")


def signal_outbox_wake():
    """Wake the outbox poller for immediate processing."""
    print("[OUTBOX] Wake signal received")
    _outbox_wake_event.set()


def start_outbox_service():
    """Launch the background outbox service daemon thread (idempotent)."""
    global _outbox_thread

    if _outbox_thread is not None and _outbox_thread.is_alive():
        print("[OUTBOX] Service already running, skipping start")
        return

    _outbox_stop_event.clear()
    _outbox_wake_event.clear()

    _outbox_thread = threading.Thread(
        target=_outbox_loop,
        name="OutboxDispatcher",
        daemon=True,
    )
    _outbox_thread.start()
    print("[OUTBOX] Service started")


def stop_outbox_service():
    """Gracefully stop the background outbox service daemon thread."""
    global _outbox_thread

    print("[OUTBOX] Stopping service...")
    _outbox_stop_event.set()
    _outbox_wake_event.set()

    if _outbox_thread and _outbox_thread.is_alive():
        _outbox_thread.join(timeout=5)

    _outbox_thread = None
    print("[OUTBOX] Service stopped")
