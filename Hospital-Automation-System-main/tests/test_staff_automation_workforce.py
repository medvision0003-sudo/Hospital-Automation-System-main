from datetime import date, datetime, time, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.models.department import Department
from app.models.employee import Employee
from app.models.enums import (
    AgentActionStatusEnum,
    AssignmentStatusEnum,
    CheckinStatusEnum,
    EmploymentStatusEnum,
    FrequencyTypeEnum,
    GenderEnum,
    HospitalEventEnum,
    PriorityEnum,
    RosterStatusEnum,
    TaskProofStatusEnum,
    TaskStatusEnum,
    TaskTypeEnum,
    WorkQueueStatusEnum,
)
from app.models.department_work_queue import DepartmentWorkQueue
from app.models.agent_action_log import AgentActionLog
from app.models.event_log import EventLog
from app.models.orchestrator_trace import OrchestratorTrace
from app.models.outbox_event import OutboxEvent
from app.models.shift import Shift
from app.models.shift_roster import ShiftRoster
from app.models.task_assignment import TaskAssignment
from app.models.task_master import TaskMaster
from app.models.task_proof import TaskProof
from app.models.task_schedule import TaskSchedule
from app.models.worker_checkin import WorkerCheckin
from app.models.worker_memory import WorkerMemory
from app.models.whatsapp_message import WhatsAppMessage
from app.agents.workforce_agent import checkin_worker, get_candidate, mark_worker_absent
from app.agents import assignment_agent
from app.agents.event_agent import publish_event
from app.agents.task_management_agent import complete_work_item
from app.core.security import verify_password
from app.orchestrator.execution import AgentExecutionError
from app.models.user import User


def test_staff_automation_deep_link_serves_react_app():
    response = TestClient(app).get("/staff-automation")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_api_health_check_verifies_database_connection(monkeypatch):
    executed = []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, statement):
            executed.append(str(statement))

    class FakeEngine:
        def connect(self):
            return FakeConnection()

    monkeypatch.setattr("app.main.engine", FakeEngine())

    assert health_check() == {"status": "ok"}
    assert executed == ["SELECT 1"]


def test_production_admin_bootstrap_requires_explicit_password(
    workforce_session,
    monkeypatch,
):
    session_local, _ = workforce_session
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("INITIAL_ADMIN_PASSWORD", raising=False)

    with session_local() as db:
        with pytest.raises(RuntimeError, match="INITIAL_ADMIN_PASSWORD"):
            seed_initial_admin(db)
        assert db.query(User).count() == 0


def test_production_admin_bootstrap_hashes_configured_password(
    workforce_session,
    monkeypatch,
):
    session_local, _ = workforce_session
    password = "A-secure-bootstrap-passphrase"
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", password)

    with session_local() as db:
        assert seed_initial_admin(db) is True
        admin = db.query(User).filter_by(email="admin@hospital.com").one()
        assert admin.hashed_password != password
        assert verify_password(password, admin.hashed_password)
from app.models.outbox_event import OutboxEvent
from app.services.outbox_dispatcher import run_absentee_watcher, run_shift_start_watcher
from app.services.outbox_dispatcher import process_pending_outbox_events
from app.services.recurring_task_scheduler import generate_scheduled_tasks
from app.services import whatsapp_service
from app.main import app, health_check, seed_initial_admin


@pytest.fixture
def workforce_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine)

    with session_local() as db:
        department = Department(department_name="Staff Automation Test")
        db.add(department)
        db.flush()
        employee = Employee(
            department_id=department.department_id,
            name="Rostered Nurse",
            role="Nurse",
            availability=EmploymentStatusEnum.ACTIVE,
            gender=GenderEnum.FEMALE,
            skill="ACLS",
        )
        shift = Shift(
            department_id=department.department_id,
            shift_name="Test Night",
            start_time=time(23, 0),
            end_time=time(7, 0),
        )
        db.add_all([employee, shift])
        db.commit()
        context = {
            "department_id": department.department_id,
            "employee_id": employee.employee_id,
            "shift_id": shift.shift_id,
        }

    try:
        yield session_local, context
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _add_checked_in_worker(db, context, now, name, skill):
    base = datetime.combine(date(2000, 1, 1), now.time())
    shift_start = (base - timedelta(hours=1)).time()
    shift_end = (base + timedelta(hours=3)).time()
    work_date = (
        date.today() - timedelta(days=1)
        if shift_start > shift_end and now.time() < shift_end
        else date.today()
    )
    shift = db.get(Shift, context["shift_id"])
    shift.start_time = shift_start
    shift.end_time = shift_end

    worker = Employee(
        department_id=context["department_id"],
        name=name,
        role="Nurse",
        availability=EmploymentStatusEnum.ACTIVE,
        gender=GenderEnum.FEMALE,
        skill=skill,
    )
    db.add(worker)
    db.flush()
    db.add_all([
        ShiftRoster(
            employee_id=worker.employee_id,
            shift_id=context["shift_id"],
            work_date=work_date,
            roster_status=RosterStatusEnum.CHECKED_IN,
        ),
        WorkerCheckin(
            device_id=f"CHECKIN-{worker.employee_id}",
            employee_id=worker.employee_id,
            checkin_time=now - timedelta(minutes=15),
            status=CheckinStatusEnum.CHECKED_IN,
        ),
    ])
    return worker


def test_checkin_requires_a_current_or_scheduled_roster(workforce_session):
    session_local, context = workforce_session

    with session_local() as db:
        with pytest.raises(ValueError, match="No roster entry"):
            checkin_worker(
                context["employee_id"],
                db,
                current_time=datetime.now(),
            )
        assert db.query(WorkerCheckin).count() == 0


def test_overnight_checkin_uses_previous_work_date_and_actual_time(workforce_session):
    session_local, context = workforce_session
    now = datetime.combine(date.today(), time(1, 0))

    with session_local() as db:
        db.add(ShiftRoster(
            employee_id=context["employee_id"],
            shift_id=context["shift_id"],
            work_date=date.today() - timedelta(days=1),
            roster_status=RosterStatusEnum.SCHEDULED,
        ))
        db.commit()

        result = checkin_worker(
            context["employee_id"],
            db,
            device_id="NIGHT-DEVICE",
            current_time=now,
        )

        checkin = db.query(WorkerCheckin).one()
        assert result["roster_id"] is not None
        assert checkin.checkin_time == now
        assert checkin.status == CheckinStatusEnum.CHECKED_IN


@pytest.mark.parametrize(
    ("checkin_time", "expected_status"),
    [
        (time(6, 0), RosterStatusEnum.CHECKED_IN),
        (time(7, 30), RosterStatusEnum.CHECKED_IN),
        (time(7, 31), RosterStatusEnum.CHECKED_IN),
        (time(9, 0), RosterStatusEnum.CHECKED_IN),
        (time(9, 1), RosterStatusEnum.HALF_DAY),
    ],
)
def test_day_shift_checkin_thresholds(workforce_session, checkin_time, expected_status):
    session_local, context = workforce_session
    shift_date = date.today()
    checkin_at = datetime.combine(shift_date, checkin_time)

    with session_local() as db:
        morning_shift = Shift(
            department_id=context["department_id"],
            shift_name="Test Morning",
            start_time=time(7, 0),
            end_time=time(15, 0),
        )
        db.add(morning_shift)
        db.flush()
        roster = ShiftRoster(
            employee_id=context["employee_id"],
            shift_id=morning_shift.shift_id,
            work_date=shift_date,
            roster_status=RosterStatusEnum.SCHEDULED,
        )
        db.add(roster)
        db.commit()

        checkin_worker(
            context["employee_id"],
            db,
            device_id="THRESHOLD-DEVICE",
            current_time=checkin_at,
        )

        db.refresh(roster)
        assert roster.roster_status == expected_status


def test_candidate_requires_current_shift_and_active_checkin(workforce_session):
    session_local, context = workforce_session
    now = datetime.combine(date.today(), time(1, 0))

    with session_local() as db:
        db.add(ShiftRoster(
            employee_id=context["employee_id"],
            shift_id=context["shift_id"],
            work_date=date.today() - timedelta(days=1),
            roster_status=RosterStatusEnum.CHECKED_IN,
        ))
        db.add(WorkerCheckin(
            device_id="NIGHT-DEVICE",
            employee_id=context["employee_id"],
            checkin_time=now - timedelta(minutes=30),
            status=CheckinStatusEnum.CHECKED_IN,
        ))
        db.commit()

        result = get_candidate(
            department_id=context["department_id"],
            db=db,
            current_time=now,
        )

        assert [candidate["employee_id"] for candidate in result["candidates"]] == [
            context["employee_id"]
        ]


def test_candidate_enforces_task_required_role(workforce_session):
    session_local, context = workforce_session
    now = datetime.combine(date.today(), time(1, 0))

    with session_local() as db:
        db.add(ShiftRoster(
            employee_id=context["employee_id"],
            shift_id=context["shift_id"],
            work_date=date.today() - timedelta(days=1),
            roster_status=RosterStatusEnum.CHECKED_IN,
        ))
        db.add(WorkerCheckin(
            device_id="NIGHT-DEVICE",
            employee_id=context["employee_id"],
            checkin_time=now - timedelta(minutes=30),
            status=CheckinStatusEnum.CHECKED_IN,
        ))
        nurse_task = TaskMaster(
            department_id=context["department_id"],
            task_name="Nurse-only task",
            priority_category=PriorityEnum.MEDIUM,
            task_type=TaskTypeEnum.RECURRING,
            task_state=TaskStatusEnum.ACTIVE,
            required_role="nurse",
        )
        doctor_task = TaskMaster(
            department_id=context["department_id"],
            task_name="Doctor-only task",
            priority_category=PriorityEnum.MEDIUM,
            task_type=TaskTypeEnum.RECURRING,
            task_state=TaskStatusEnum.ACTIVE,
            required_role="Doctor",
        )
        db.add_all([nurse_task, doctor_task])
        db.commit()

        nurse_result = get_candidate(
            department_id=context["department_id"],
            db=db,
            current_time=now,
            task_id=nurse_task.task_id,
        )
        doctor_result = get_candidate(
            department_id=context["department_id"],
            db=db,
            current_time=now,
            task_id=doctor_task.task_id,
        )

        assert [candidate["employee_id"] for candidate in nurse_result["candidates"]] == [
            context["employee_id"]
        ]
        assert nurse_result["required_role"] == "nurse"
        assert doctor_result["candidates"] == []
        assert doctor_result["escalation_required"] is True
        assert doctor_result["required_role"] == "Doctor"


def test_candidate_accepts_similar_skill_before_escalating(workforce_session):
    session_local, context = workforce_session
    now = datetime.combine(date.today(), time(1, 0))

    with session_local() as db:
        employee = db.get(Employee, context["employee_id"])
        employee.skill = "VITAL_SIGNS"

        db.add(ShiftRoster(
            employee_id=context["employee_id"],
            shift_id=context["shift_id"],
            work_date=date.today() - timedelta(days=1),
            roster_status=RosterStatusEnum.CHECKED_IN,
        ))
        db.add(WorkerCheckin(
            device_id="NIGHT-DEVICE",
            employee_id=context["employee_id"],
            checkin_time=now - timedelta(minutes=30),
            status=CheckinStatusEnum.CHECKED_IN,
        ))
        colleague = Employee(
            department_id=context["department_id"],
            name="Similar Skill Colleague",
            role="Nurse",
            availability=EmploymentStatusEnum.ACTIVE,
            gender=GenderEnum.FEMALE,
            skill="BLS",
        )
        db.add(colleague)
        db.flush()
        db.add_all([
            ShiftRoster(
                employee_id=colleague.employee_id,
                shift_id=context["shift_id"],
                work_date=date.today() - timedelta(days=1),
                roster_status=RosterStatusEnum.CHECKED_IN,
            ),
            WorkerCheckin(
                device_id="SIMILAR-SKILL-CHECKIN",
                employee_id=colleague.employee_id,
                checkin_time=now - timedelta(minutes=15),
                status=CheckinStatusEnum.CHECKED_IN,
            ),
        ])
        task = TaskMaster(
            department_id=context["department_id"],
            task_name="Advanced cardiac response",
            priority_category=PriorityEnum.HIGH,
            task_type=TaskTypeEnum.RECURRING,
            task_state=TaskStatusEnum.ACTIVE,
            required_skill="ACLS",
        )
        db.add(task)
        db.commit()

        result = get_candidate(
            department_id=context["department_id"],
            db=db,
            current_time=now,
            task_id=task.task_id,
        )

        assert result["escalation_required"] is False
        assert [candidate["employee_id"] for candidate in result["candidates"]] == [
            colleague.employee_id,
        ]
        assert result["candidates"][0]["match_source"] == "SIMILAR_SKILL"


def test_assignment_reasoning_prompt_includes_employee_skill_and_experience():
    prompt = assignment_agent._build_reasoning_prompt(
        task_name="Vital Signs Monitoring",
        task_description="Record the assigned observation set.",
        priority="HIGH",
        candidates=[
            {
                "employee_id": 17,
                "role": "NURSE",
                "skill": "VITAL_SIGNS, ACLS",
                "experience_years": 8,
                "pending_task": 2,
                "total_task_completed": 34,
                "match_source": "STATIC_PROFILE",
            },
        ],
    )

    assert "VITAL_SIGNS, ACLS" in prompt
    assert "Experience: 8 years" in prompt
    assert "Static skill match" in prompt
    assert "Evaluate each candidate's listed role, skills, match type, and years of experience" in prompt
    assert "prefer greater relevant experience" in prompt


def test_candidate_excludes_rostered_worker_outside_shift(workforce_session):
    session_local, context = workforce_session
    now = datetime.combine(date.today(), time(12, 0))

    with session_local() as db:
        db.add(ShiftRoster(
            employee_id=context["employee_id"],
            shift_id=context["shift_id"],
            work_date=date.today(),
            roster_status=RosterStatusEnum.CHECKED_IN,
        ))
        db.add(WorkerCheckin(
            device_id="NIGHT-DEVICE",
            employee_id=context["employee_id"],
            checkin_time=now - timedelta(hours=1),
            status=CheckinStatusEnum.CHECKED_IN,
        ))
        db.commit()

        result = get_candidate(
            department_id=context["department_id"],
            db=db,
            current_time=now,
        )

        assert result["candidates"] == []
        assert result["escalation_required"] is True


def test_marking_absent_releases_unstarted_work_only(workforce_session):
    session_local, context = workforce_session

    with session_local() as db:
        roster = ShiftRoster(
            employee_id=context["employee_id"],
            shift_id=context["shift_id"],
            work_date=date.today(),
            roster_status=RosterStatusEnum.SCHEDULED,
        )
        task = TaskMaster(
            department_id=context["department_id"],
            task_name="Absence reassignment test",
            priority_category=PriorityEnum.HIGH,
            task_type=TaskTypeEnum.RECURRING,
            task_state=TaskStatusEnum.ACTIVE,
        )
        db.add_all([roster, task])
        db.flush()

        assigned_work = DepartmentWorkQueue(
            task_id=task.task_id,
            department_id=context["department_id"],
            priority=PriorityEnum.HIGH,
            queue_status=WorkQueueStatusEnum.ASSIGNED,
        )
        in_progress_work = DepartmentWorkQueue(
            task_id=task.task_id,
            department_id=context["department_id"],
            priority=PriorityEnum.HIGH,
            queue_status=WorkQueueStatusEnum.ASSIGNED,
        )
        db.add_all([assigned_work, in_progress_work])
        db.flush()
        db.add_all([
            TaskAssignment(
                work_id=assigned_work.work_id,
                employee_id=context["employee_id"],
                assignment_status=AssignmentStatusEnum.ASSIGNED,
            ),
            TaskAssignment(
                work_id=in_progress_work.work_id,
                employee_id=context["employee_id"],
                assignment_status=AssignmentStatusEnum.IN_PROGRESS,
            ),
        ])
        db.commit()

        result = mark_worker_absent(roster.roster_id, db)

        assert result["released_work_ids"] == [assigned_work.work_id]
        assert assigned_work.queue_status == WorkQueueStatusEnum.PENDING_ASSIGNED
        assignments = db.query(TaskAssignment).order_by(TaskAssignment.assignment_id).all()
        assert assignments[0].assignment_status == AssignmentStatusEnum.PREEMPTED
        assert assignments[1].assignment_status == AssignmentStatusEnum.IN_PROGRESS


def test_shift_start_watcher_emits_one_re_evaluation_event(workforce_session):
    session_local, context = workforce_session

    with session_local() as db:
        shift = Shift(
            department_id=context["department_id"],
            shift_name="All-day test window",
            start_time=time(0, 0),
            end_time=time(23, 59, 59),
        )
        db.add(shift)
        db.flush()
        roster = ShiftRoster(
            employee_id=context["employee_id"],
            shift_id=shift.shift_id,
            work_date=date.today(),
            roster_status=RosterStatusEnum.SCHEDULED,
        )
        db.add(roster)
        db.commit()

        run_shift_start_watcher(db)
        run_shift_start_watcher(db)

        events = db.query(OutboxEvent).filter(
            OutboxEvent.event_type == "SHIFT_STARTED",
            OutboxEvent.dedupe_key == f"SHIFT_STARTED:roster_id={roster.roster_id}",
        ).all()
        assert len(events) == 1


def test_absentee_watcher_detects_overnight_roster_after_midnight(workforce_session):
    session_local, context = workforce_session
    now = datetime.combine(date.today(), time(0, 30))

    with session_local() as db:
        roster = ShiftRoster(
            employee_id=context["employee_id"],
            shift_id=context["shift_id"],
            work_date=date.today() - timedelta(days=1),
            roster_status=RosterStatusEnum.SCHEDULED,
        )
        db.add(roster)
        db.commit()

        run_absentee_watcher(db, current_time=now)

        event = db.query(OutboxEvent).filter(
            OutboxEvent.event_type == HospitalEventEnum.STAFF_ABSENT_DETECTED.value,
        ).one()
        assert f'"roster_id": {roster.roster_id}' in event.payload_json


def test_absent_worker_tasks_are_reassigned_to_checked_in_colleague(
    workforce_session,
    monkeypatch,
):
    session_local, context = workforce_session
    now = datetime.now().replace(microsecond=0)
    base = datetime.combine(date(2000, 1, 1), now.time())
    shift_start = (base - timedelta(hours=1)).time()
    shift_end = (base + timedelta(hours=2)).time()
    work_date = (
        date.today() - timedelta(days=1)
        if shift_start > shift_end and now.time() < shift_end
        else date.today()
    )

    def offline_reasoning(**kwargs):
        raise RuntimeError("offline test fallback")

    monkeypatch.setattr(assignment_agent, "_select_candidate_with_reasoning", offline_reasoning)

    with session_local() as db:
        shift = db.get(Shift, context["shift_id"])
        shift.start_time = shift_start
        shift.end_time = shift_end
        absent_roster = ShiftRoster(
            employee_id=context["employee_id"],
            shift_id=context["shift_id"],
            work_date=work_date,
            roster_status=RosterStatusEnum.SCHEDULED,
        )
        colleague = Employee(
            department_id=context["department_id"],
            name="Checked-in colleague",
            role="Nurse",
            availability=EmploymentStatusEnum.ACTIVE,
            gender=GenderEnum.FEMALE,
            skill="ACLS",
        )
        db.add_all([absent_roster, colleague])
        db.flush()
        colleague_roster = ShiftRoster(
            employee_id=colleague.employee_id,
            shift_id=context["shift_id"],
            work_date=work_date,
            roster_status=RosterStatusEnum.CHECKED_IN,
        )
        task = TaskMaster(
            department_id=context["department_id"],
            task_name="Reassignment after absence",
            priority_category=PriorityEnum.HIGH,
            task_type=TaskTypeEnum.RECURRING,
            required_skill="ACLS",
            task_state=TaskStatusEnum.ACTIVE,
        )
        checkin = WorkerCheckin(
            device_id="COLLEAGUE-CHECKIN",
            employee_id=colleague.employee_id,
            checkin_time=now - timedelta(minutes=15),
            status=CheckinStatusEnum.CHECKED_IN,
        )
        db.add_all([colleague_roster, task, checkin])
        db.flush()
        work = DepartmentWorkQueue(
            task_id=task.task_id,
            department_id=context["department_id"],
            shift_id=context["shift_id"],
            priority=PriorityEnum.HIGH,
            queue_status=WorkQueueStatusEnum.ASSIGNED,
        )
        db.add(work)
        db.flush()
        old_assignment = TaskAssignment(
            work_id=work.work_id,
            employee_id=context["employee_id"],
            assignment_status=AssignmentStatusEnum.ASSIGNED,
        )
        db.add(old_assignment)
        db.commit()

        result = publish_event(
            HospitalEventEnum.STAFF_ABSENT_DETECTED,
            {"roster_id": absent_roster.roster_id},
            db,
        )

        assert result["status"] == "SUCCESS"
        db.refresh(work)
        assert absent_roster.roster_status == RosterStatusEnum.ABSENT
        assert old_assignment.assignment_status == AssignmentStatusEnum.PREEMPTED
        assert work.queue_status == WorkQueueStatusEnum.ASSIGNED
        active_assignment = db.query(TaskAssignment).filter(
            TaskAssignment.work_id == work.work_id,
            TaskAssignment.assignment_status == AssignmentStatusEnum.ASSIGNED,
        ).one()
        assert active_assignment.employee_id == colleague.employee_id
        assert db.query(AgentActionLog).filter(
            AgentActionLog.action_type == "ASSIGN_TASK",
            AgentActionLog.decision_summary.contains(
                "reassignment_reason=scheduled employee marked absent"
            ),
        ).count() == 1
        assert db.query(AgentActionLog).filter(
            AgentActionLog.workflow_id == result["workflow_id"],
            AgentActionLog.action_type == "ESCALATION",
        ).count() == 0
        assert db.query(AgentActionLog).filter(
            AgentActionLog.workflow_id == result["workflow_id"],
            AgentActionLog.action_type == "STAFF_ABSENCE_HANDLED",
            AgentActionLog.execution_status == "SUCCESS",
        ).count() == 1


def test_absent_worker_tasks_escalate_when_no_replacement_is_eligible(workforce_session):
    session_local, context = workforce_session
    now = datetime.now().replace(microsecond=0)
    base = datetime.combine(date(2000, 1, 1), now.time())
    shift_start = (base - timedelta(hours=1)).time()
    shift_end = (base + timedelta(hours=2)).time()
    work_date = (
        date.today() - timedelta(days=1)
        if shift_start > shift_end and now.time() < shift_end
        else date.today()
    )

    with session_local() as db:
        shift = db.get(Shift, context["shift_id"])
        shift.start_time = shift_start
        shift.end_time = shift_end
        roster = ShiftRoster(
            employee_id=context["employee_id"],
            shift_id=context["shift_id"],
            work_date=work_date,
            roster_status=RosterStatusEnum.SCHEDULED,
        )
        off_shift_worker = Employee(
            department_id=context["department_id"],
            name="Qualified but off-shift worker",
            role="Nurse",
            availability=EmploymentStatusEnum.ACTIVE,
            gender=GenderEnum.FEMALE,
            skill="ACLS",
        )
        off_shift = Shift(
            department_id=context["department_id"],
            shift_name="Different shift",
            start_time=shift_start,
            end_time=shift_end,
        )
        task = TaskMaster(
            department_id=context["department_id"],
            task_name="Escalate absent worker task",
            priority_category=PriorityEnum.HIGH,
            task_type=TaskTypeEnum.RECURRING,
            required_skill="ACLS",
            task_state=TaskStatusEnum.ACTIVE,
        )
        db.add_all([roster, task, off_shift_worker, off_shift])
        db.flush()
        db.add_all([
            ShiftRoster(
                employee_id=off_shift_worker.employee_id,
                shift_id=off_shift.shift_id,
                work_date=work_date,
                roster_status=RosterStatusEnum.CHECKED_IN,
            ),
            WorkerCheckin(
                device_id="OFF-SHIFT-CHECKIN",
                employee_id=off_shift_worker.employee_id,
                checkin_time=now - timedelta(minutes=15),
                status=CheckinStatusEnum.CHECKED_IN,
            ),
        ])
        work = DepartmentWorkQueue(
            task_id=task.task_id,
            department_id=context["department_id"],
            shift_id=context["shift_id"],
            priority=PriorityEnum.HIGH,
            queue_status=WorkQueueStatusEnum.ASSIGNED,
        )
        db.add(work)
        db.flush()
        db.add(TaskAssignment(
            work_id=work.work_id,
            employee_id=context["employee_id"],
            assignment_status=AssignmentStatusEnum.ASSIGNED,
        ))
        db.commit()

        result = publish_event(
            HospitalEventEnum.STAFF_ABSENT_DETECTED,
            {"roster_id": roster.roster_id},
            db,
        )

        assert result["status"] == "FAILED"
        escalation = db.query(AgentActionLog).filter(
            AgentActionLog.agent_id == 2,
            AgentActionLog.action_type == "ESCALATION",
            AgentActionLog.execution_status == "FAILED",
        ).one()
        assert f"work_id={work.work_id}" in escalation.decision_summary
        db.refresh(work)
        assert work.queue_status == WorkQueueStatusEnum.PENDING_ASSIGNED


def test_timeout_automatically_reassigns_unstarted_work_to_qualified_worker(
    workforce_session,
    monkeypatch,
):
    session_local, context = workforce_session
    now = datetime.now().replace(microsecond=0)
    monkeypatch.setattr(
        assignment_agent,
        "_select_candidate_with_reasoning",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("offline test fallback")),
    )

    with session_local() as db:
        qualified = _add_checked_in_worker(
            db, context, now, "Qualified replacement", "ACLS"
        )
        _add_checked_in_worker(db, context, now, "Wrong skill worker", "INVENTORY")
        task = TaskMaster(
            department_id=context["department_id"],
            task_name="Overdue qualified task",
            priority_category=PriorityEnum.HIGH,
            task_type=TaskTypeEnum.RECURRING,
            required_skill="ACLS",
            task_state=TaskStatusEnum.ACTIVE,
        )
        db.add(task)
        db.flush()
        work = DepartmentWorkQueue(
            task_id=task.task_id,
            department_id=context["department_id"],
            shift_id=context["shift_id"],
            priority=PriorityEnum.HIGH,
            queue_status=WorkQueueStatusEnum.ASSIGNED,
            due_date=now - timedelta(minutes=1),
        )
        db.add(work)
        db.flush()
        original = TaskAssignment(
            work_id=work.work_id,
            employee_id=context["employee_id"],
            assignment_status=AssignmentStatusEnum.ASSIGNED,
        )
        db.add(original)
        db.commit()

        result = publish_event(
            HospitalEventEnum.TASK_TIMEOUT_DETECTED,
            {"work_id": work.work_id},
            db,
        )

        assert result["status"] == "SUCCESS"
        db.refresh(work)
        assert work.queue_status == WorkQueueStatusEnum.ASSIGNED
        assert original.assignment_status == AssignmentStatusEnum.PREEMPTED
        active = db.query(TaskAssignment).filter(
            TaskAssignment.work_id == work.work_id,
            TaskAssignment.assignment_status == AssignmentStatusEnum.ASSIGNED,
        ).one()
        assert active.employee_id == qualified.employee_id
        assert db.query(AgentActionLog).filter(
            AgentActionLog.workflow_id == result["workflow_id"],
            AgentActionLog.action_type == "AUTOMATIC_REASSIGNMENT",
            AgentActionLog.is_resolved.is_(True),
        ).count() == 1
        assert db.query(AgentActionLog).filter(
            AgentActionLog.workflow_id == result["workflow_id"],
            AgentActionLog.action_type == "ESCALATION",
        ).count() == 0

        retry = assignment_agent.automate_work_item_assignment(
            work_id=work.work_id,
            db=db,
            workflow_id=result["workflow_id"],
            trigger="TASK_TIMEOUT",
            reassign_unstarted=True,
        )
        assert retry["action"] == "ALREADY_PROCESSED"
        assert db.query(TaskAssignment).filter(
            TaskAssignment.work_id == work.work_id,
            TaskAssignment.assignment_status == AssignmentStatusEnum.ASSIGNED,
        ).count() == 1


def test_staff_shortage_escalates_if_no_skill_matched_worker_is_available(
    workforce_session,
):
    session_local, context = workforce_session
    now = datetime.now().replace(microsecond=0)

    with session_local() as db:
        _add_checked_in_worker(db, context, now, "Unqualified worker", "INVENTORY")
        task = TaskMaster(
            department_id=context["department_id"],
            task_name="Skill-gated pending task",
            priority_category=PriorityEnum.HIGH,
            task_type=TaskTypeEnum.RECURRING,
            required_skill="ACLS",
            task_state=TaskStatusEnum.ACTIVE,
        )
        db.add(task)
        db.flush()
        work = DepartmentWorkQueue(
            task_id=task.task_id,
            department_id=context["department_id"],
            shift_id=context["shift_id"],
            priority=PriorityEnum.HIGH,
            queue_status=WorkQueueStatusEnum.PENDING_ASSIGNED,
        )
        db.add(work)
        db.commit()

        result = publish_event(
            HospitalEventEnum.STAFF_SHORTAGE_DETECTED,
            {"work_id": work.work_id},
            db,
        )

        db.refresh(work)
        assert work.queue_status == WorkQueueStatusEnum.PENDING_ASSIGNED
        assert db.query(TaskAssignment).filter(
            TaskAssignment.work_id == work.work_id,
            TaskAssignment.assignment_status.in_([
                AssignmentStatusEnum.ASSIGNED,
                AssignmentStatusEnum.IN_PROGRESS,
            ]),
        ).count() == 0
        escalation = db.query(AgentActionLog).filter(
            AgentActionLog.workflow_id == result["workflow_id"],
            AgentActionLog.action_type == "ESCALATION",
            AgentActionLog.is_resolved.is_(False),
        ).one()
        assert f"work_id={work.work_id}" in escalation.decision_summary
        assert "ACLS" in escalation.decision_summary


def test_staff_shortage_automatically_assigns_pending_work(
    workforce_session,
    monkeypatch,
):
    session_local, context = workforce_session
    now = datetime.now().replace(microsecond=0)
    monkeypatch.setattr(
        assignment_agent,
        "_select_candidate_with_reasoning",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("offline test fallback")),
    )

    with session_local() as db:
        qualified = _add_checked_in_worker(
            db, context, now, "Qualified shortage replacement", "ACLS"
        )
        task = TaskMaster(
            department_id=context["department_id"],
            task_name="Staff shortage recovery task",
            priority_category=PriorityEnum.HIGH,
            task_type=TaskTypeEnum.RECURRING,
            required_skill="ACLS",
            task_state=TaskStatusEnum.ACTIVE,
        )
        db.add(task)
        db.flush()
        work = DepartmentWorkQueue(
            task_id=task.task_id,
            department_id=context["department_id"],
            shift_id=context["shift_id"],
            priority=PriorityEnum.HIGH,
            queue_status=WorkQueueStatusEnum.PENDING_ASSIGNED,
        )
        db.add(work)
        db.commit()

        result = publish_event(
            HospitalEventEnum.STAFF_SHORTAGE_DETECTED,
            {"work_id": work.work_id},
            db,
        )

        assert result["status"] == "SUCCESS"
        db.refresh(work)
        assert work.queue_status == WorkQueueStatusEnum.ASSIGNED
        assignment = db.query(TaskAssignment).filter(
            TaskAssignment.work_id == work.work_id,
            TaskAssignment.assignment_status == AssignmentStatusEnum.ASSIGNED,
        ).one()
        assert assignment.employee_id == qualified.employee_id
        assert db.query(AgentActionLog).filter(
            AgentActionLog.workflow_id == result["workflow_id"],
            AgentActionLog.action_type == "AUTOMATIC_REASSIGNMENT",
            AgentActionLog.is_resolved.is_(True),
        ).count() == 1
        assert db.query(AgentActionLog).filter(
            AgentActionLog.workflow_id == result["workflow_id"],
            AgentActionLog.action_type == "ESCALATION",
        ).count() == 0


def test_timeout_does_not_interrupt_in_progress_work(workforce_session):
    session_local, context = workforce_session
    now = datetime.now().replace(microsecond=0)

    with session_local() as db:
        task = TaskMaster(
            department_id=context["department_id"],
            task_name="In-progress overdue task",
            priority_category=PriorityEnum.HIGH,
            task_type=TaskTypeEnum.RECURRING,
            task_state=TaskStatusEnum.ACTIVE,
        )
        db.add(task)
        db.flush()
        work = DepartmentWorkQueue(
            task_id=task.task_id,
            department_id=context["department_id"],
            shift_id=context["shift_id"],
            priority=PriorityEnum.HIGH,
            queue_status=WorkQueueStatusEnum.ASSIGNED,
            due_date=now - timedelta(minutes=1),
        )
        db.add(work)
        db.flush()
        assignment = TaskAssignment(
            work_id=work.work_id,
            employee_id=context["employee_id"],
            assignment_status=AssignmentStatusEnum.IN_PROGRESS,
        )
        db.add(assignment)
        db.commit()

        result = publish_event(
            HospitalEventEnum.TASK_TIMEOUT_DETECTED,
            {"work_id": work.work_id},
            db,
        )

        db.refresh(work)
        db.refresh(assignment)
        assert work.queue_status == WorkQueueStatusEnum.ASSIGNED
        assert assignment.assignment_status == AssignmentStatusEnum.IN_PROGRESS
        assert db.query(AgentActionLog).filter(
            AgentActionLog.workflow_id == result["workflow_id"],
            AgentActionLog.action_type == "ESCALATION",
            AgentActionLog.is_resolved.is_(False),
        ).count() == 1


def test_checkout_reassigns_incomplete_work_to_available_colleague(
    workforce_session,
    monkeypatch,
):
    session_local, context = workforce_session
    now = datetime.now().replace(microsecond=0)
    base = datetime.combine(date(2000, 1, 1), now.time())
    shift_start = (base - timedelta(hours=1)).time()
    shift_end = (base + timedelta(hours=2)).time()
    work_date = (
        date.today() - timedelta(days=1)
        if shift_start > shift_end and now.time() < shift_end
        else date.today()
    )

    def offline_reasoning(**kwargs):
        raise RuntimeError("offline test fallback")

    monkeypatch.setattr(
        assignment_agent,
        "_select_candidate_with_reasoning",
        offline_reasoning,
    )

    with session_local() as db:
        shift = db.get(Shift, context["shift_id"])
        shift.start_time = shift_start
        shift.end_time = shift_end
        outgoing_roster = ShiftRoster(
            employee_id=context["employee_id"],
            shift_id=context["shift_id"],
            work_date=work_date,
            roster_status=RosterStatusEnum.CHECKED_IN,
        )
        colleague = Employee(
            department_id=context["department_id"],
            name="Available replacement",
            role="Nurse",
            availability=EmploymentStatusEnum.ACTIVE,
            gender=GenderEnum.FEMALE,
            skill="ACLS",
        )
        colleague_shift = Shift(
            department_id=context["department_id"],
            shift_name="Replacement Shift",
            start_time=shift_start,
            end_time=shift_end,
        )
        db.add_all([outgoing_roster, colleague, colleague_shift])
        db.flush()
        db.add_all([
            ShiftRoster(
                employee_id=colleague.employee_id,
                shift_id=colleague_shift.shift_id,
                work_date=work_date,
                roster_status=RosterStatusEnum.CHECKED_IN,
            ),
            WorkerCheckin(
                device_id="OUTGOING-CHECKIN",
                employee_id=context["employee_id"],
                checkin_time=now - timedelta(minutes=30),
                status=CheckinStatusEnum.CHECKED_IN,
            ),
            WorkerCheckin(
                device_id="COLLEAGUE-CHECKIN",
                employee_id=colleague.employee_id,
                checkin_time=now - timedelta(minutes=20),
                status=CheckinStatusEnum.CHECKED_IN,
            ),
        ])
        task = TaskMaster(
            department_id=context["department_id"],
            task_name="Checkout reassignment task",
            priority_category=PriorityEnum.HIGH,
            task_type=TaskTypeEnum.RECURRING,
            required_skill="ACLS",
            task_state=TaskStatusEnum.ACTIVE,
        )
        db.add(task)
        db.flush()
        work = DepartmentWorkQueue(
            task_id=task.task_id,
            department_id=context["department_id"],
            shift_id=context["shift_id"],
            priority=PriorityEnum.HIGH,
            queue_status=WorkQueueStatusEnum.ASSIGNED,
        )
        db.add(work)
        db.flush()
        old_assignment = TaskAssignment(
            work_id=work.work_id,
            employee_id=context["employee_id"],
            assignment_status=AssignmentStatusEnum.IN_PROGRESS,
        )
        db.add(old_assignment)
        db.commit()

        result = publish_event(
            HospitalEventEnum.WORKER_CHECKED_OUT,
            {
                "employee_id": context["employee_id"],
                "occurred_at": (now + timedelta(minutes=15)).isoformat(),
                "trigger_source": "MANUAL_OVERRIDE",
                "incomplete_task_action": "REASSIGN",
            },
            db,
        )

        assert result["status"] == "SUCCESS", result.get("reason")
        db.refresh(work)
        db.refresh(old_assignment)
        assert old_assignment.assignment_status == AssignmentStatusEnum.PREEMPTED
        assert work.queue_status == WorkQueueStatusEnum.ASSIGNED
        new_assignment = db.query(TaskAssignment).filter(
            TaskAssignment.work_id == work.work_id,
            TaskAssignment.assignment_status == AssignmentStatusEnum.ASSIGNED,
        ).one()
        assert new_assignment.employee_id == colleague.employee_id
        outgoing_memory = db.get(WorkerMemory, context["employee_id"])
        colleague_memory = db.get(WorkerMemory, colleague.employee_id)
        assert outgoing_memory is not None
        assert outgoing_memory.pending_task == 0
        assert colleague_memory is not None
        assert colleague_memory.pending_task == 1
        db.refresh(outgoing_roster)
        assert outgoing_roster.roster_status == RosterStatusEnum.COMPLETED


def test_attendance_events_assign_and_check_out_through_agents(
    workforce_session,
    monkeypatch,
):
    session_local, context = workforce_session
    now = datetime.now().replace(microsecond=0)
    base = datetime.combine(date(2000, 1, 1), now.time())
    shift_start = (base - timedelta(hours=1)).time()
    shift_end = (base + timedelta(hours=2)).time()
    work_date = (
        date.today() - timedelta(days=1)
        if shift_start > shift_end and now.time() < shift_end
        else date.today()
    )

    def offline_reasoning(**kwargs):
        raise RuntimeError("offline test fallback")

    monkeypatch.setattr(assignment_agent, "_select_candidate_with_reasoning", offline_reasoning)

    with session_local() as db:
        shift = db.get(Shift, context["shift_id"])
        shift.start_time = shift_start
        shift.end_time = shift_end
        roster = ShiftRoster(
            employee_id=context["employee_id"],
            shift_id=context["shift_id"],
            work_date=work_date,
            roster_status=RosterStatusEnum.SCHEDULED,
        )
        task = TaskMaster(
            department_id=context["department_id"],
            task_name="Pending shift task",
            priority_category=PriorityEnum.HIGH,
            task_type=TaskTypeEnum.RECURRING,
            task_state=TaskStatusEnum.ACTIVE,
        )
        db.add_all([roster, task])
        db.flush()
        work_item = DepartmentWorkQueue(
            task_id=task.task_id,
            department_id=context["department_id"],
            priority=PriorityEnum.HIGH,
            queue_status=WorkQueueStatusEnum.PENDING_ASSIGNED,
        )
        db.add(work_item)
        db.commit()
        work_id = work_item.work_id

        result = publish_event(
            HospitalEventEnum.WORKER_CHECKED_IN,
            {
                "employee_id": context["employee_id"],
                "occurred_at": now.isoformat(),
                "trigger_source": "MANUAL_OVERRIDE",
            },
            db,
        )

        assert result["status"] == "SUCCESS", result.get("reason", result.get("workflow_execution"))
        db.refresh(work_item)
        assignment = db.query(TaskAssignment).filter(
            TaskAssignment.work_id == work_id
        ).one()
        assert work_item.queue_status == WorkQueueStatusEnum.ASSIGNED
        assert assignment.employee_id == context["employee_id"]
        assert assignment.assignment_status == AssignmentStatusEnum.ASSIGNED
        assert db.query(EventLog).filter(
            EventLog.event_log == HospitalEventEnum.WORKER_CHECKED_IN.value,
            EventLog.employee_id == context["employee_id"],
            EventLog.source_module == "MANUAL_OVERRIDE",
        ).count() == 1
        assert db.query(AgentActionLog).filter(
            AgentActionLog.action_type == "WORKFORCE_CHECK",
            AgentActionLog.event_id.isnot(None),
        ).count() == 1
        checkin_trace = db.query(OrchestratorTrace).filter(
            OrchestratorTrace.event_type == HospitalEventEnum.WORKER_CHECKED_IN.value,
        ).order_by(OrchestratorTrace.started_at.desc()).first()
        assert checkin_trace is not None
        assert checkin_trace.trigger_source == "MANUAL_OVERRIDE"
        assert all(
            agent_name in checkin_trace.workflow_execution_json
            for agent_name in (
                "EVENT_AGENT",
                "WORKFORCE_AGENT",
                "TASK_MANAGEMENT_AGENT",
                "ASSIGNMENT_AGENT",
            )
        )

        monkeypatch.setattr(whatsapp_service, "WHATSAPP_MOCK", True)
        assert db.query(OutboxEvent).filter(
            OutboxEvent.event_type == HospitalEventEnum.SEND_WHATSAPP_NOTIFICATION.value,
        ).count() == 1
        assert process_pending_outbox_events(db) == 1
        notification_trace = db.query(OrchestratorTrace).filter(
            OrchestratorTrace.event_type == HospitalEventEnum.SEND_WHATSAPP_NOTIFICATION.value,
        ).one()
        assert notification_trace.execution_status == "SUCCESS"
        assert "COMMUNICATION_AGENT" in notification_trace.workflow_execution_json
        communication_action = db.query(AgentActionLog).filter(
            AgentActionLog.action_type == "WHATSAPP_TASK_NOTIFICATION",
        ).one()
        assert communication_action.workflow_id == notification_trace.workflow_id
        assert communication_action.event_id is not None
        assert db.query(WhatsAppMessage).filter(
            WhatsAppMessage.status == "MOCKED",
        ).count() == 1

        duplicate_result = publish_event(
            HospitalEventEnum.WORKER_CHECKED_IN,
            {
                "employee_id": context["employee_id"],
                "occurred_at": now.isoformat(),
                "trigger_source": "MANUAL_OVERRIDE",
            },
            db,
        )
        assert duplicate_result["status"] == "SUCCESS"
        assert db.query(WorkerCheckin).filter(
            WorkerCheckin.employee_id == context["employee_id"]
        ).count() == 1
        assert db.query(TaskAssignment).filter(
            TaskAssignment.work_id == work_id
        ).count() == 1
        assert db.query(EventLog).filter(
            EventLog.event_log == HospitalEventEnum.WORKER_CHECKED_IN.value,
            EventLog.employee_id == context["employee_id"],
        ).count() == 1

        checkout_time = now + timedelta(minutes=30)
        checkout_result = publish_event(
            HospitalEventEnum.WORKER_CHECKED_OUT,
            {
                "employee_id": context["employee_id"],
                "occurred_at": checkout_time.isoformat(),
            },
            db,
        )
        checkin = db.query(WorkerCheckin).filter(
            WorkerCheckin.employee_id == context["employee_id"]
        ).one()
        assert checkout_result["status"] == "SUCCESS"
        assert checkin.status == CheckinStatusEnum.CHECKED_OUT
        assert checkin.checkout_time == checkout_time
        assert checkout_result["work_duration_minutes"] == 30
        assert db.query(EventLog).filter(
            EventLog.event_log == HospitalEventEnum.WORKER_CHECKED_OUT.value,
            EventLog.employee_id == context["employee_id"],
        ).count() == 1
        candidates_after_checkout = get_candidate(
            department_id=context["department_id"],
            db=db,
            shift_id=context["shift_id"],
            current_time=checkout_time + timedelta(minutes=1),
        )
        assert candidates_after_checkout["candidates"] == []


def test_whatsapp_delivery_stays_mocked_without_credentials(monkeypatch):
    monkeypatch.setattr(whatsapp_service, "WHATSAPP_MOCK", False)
    monkeypatch.setattr(whatsapp_service, "WHATSAPP_ACCESS_TOKEN", "")
    monkeypatch.setattr(whatsapp_service, "WHATSAPP_PHONE_NUMBER_ID", "")

    assert whatsapp_service.is_whatsapp_mock_mode() is True


@pytest.mark.parametrize(
    ("shift_name", "start_time", "end_time", "clock_time", "day_offset", "due_offset"),
    [
        ("Morning", time(7), time(15), time(10), 0, timedelta(hours=5)),
        ("Evening", time(15), time(23), time(19), 0, timedelta(hours=4)),
        ("Night", time(23), time(7), time(1), -1, timedelta(hours=6)),
    ],
)
def test_checkin_generates_and_assigns_due_task_for_active_shift(
    workforce_session,
    monkeypatch,
    shift_name,
    start_time,
    end_time,
    clock_time,
    day_offset,
    due_offset,
):
    session_local, context = workforce_session
    work_date = date.today() + timedelta(days=day_offset)
    now = datetime.combine(date.today(), clock_time)

    def offline_reasoning(**kwargs):
        raise RuntimeError("offline test fallback")

    monkeypatch.setattr(assignment_agent, "_select_candidate_with_reasoning", offline_reasoning)

    with session_local() as db:
        shift = db.get(Shift, context["shift_id"])
        shift.shift_name = shift_name
        shift.start_time = start_time
        shift.end_time = end_time
        roster = ShiftRoster(
            employee_id=context["employee_id"],
            shift_id=shift.shift_id,
            work_date=work_date,
            roster_status=RosterStatusEnum.SCHEDULED,
        )
        task = TaskMaster(
            department_id=context["department_id"],
            task_name=f"{shift_name} operational task",
            description="Task generated from the active shift schedule.",
            priority_category=PriorityEnum.HIGH,
            estimated_time=60,
            task_type=TaskTypeEnum.RECURRING,
            required_skill="ACLS",
            task_state=TaskStatusEnum.ACTIVE,
        )
        db.add_all([roster, task])
        db.flush()
        schedule = TaskSchedule(
            task_id=task.task_id,
            shift_id=shift.shift_id,
            schedule_name=f"{shift_name} recurring schedule",
            frequency_type=FrequencyTypeEnum.HOURS,
            frequency_value=8,
            next_run=now - timedelta(minutes=1),
            is_active=True,
        )
        wrong_shift = Shift(
            department_id=context["department_id"],
            shift_name="Other shift",
            start_time=time(12),
            end_time=time(13),
        )
        wrong_task = TaskMaster(
            department_id=context["department_id"],
            task_name=f"{shift_name} other-shift task",
            priority_category=PriorityEnum.MEDIUM,
            task_type=TaskTypeEnum.RECURRING,
            task_state=TaskStatusEnum.ACTIVE,
        )
        db.add_all([schedule, wrong_shift, wrong_task])
        db.flush()
        db.add(TaskSchedule(
            task_id=wrong_task.task_id,
            shift_id=wrong_shift.shift_id,
            schedule_name="Other shift schedule",
            frequency_type=FrequencyTypeEnum.HOURS,
            frequency_value=8,
            next_run=now - timedelta(minutes=1),
            is_active=True,
        ))
        db.commit()

        result = publish_event(
            HospitalEventEnum.WORKER_CHECKED_IN,
            {
                "employee_id": context["employee_id"],
                "occurred_at": now.isoformat(),
            },
            db,
        )

        assert result["status"] == "SUCCESS", result.get("reason", result.get("workflow_execution"))
        work_item = db.query(DepartmentWorkQueue).one()
        assignment = db.query(TaskAssignment).filter(
            TaskAssignment.work_id == work_item.work_id
        ).one()
        assert work_item.task_id == task.task_id
        assert work_item.department_id == context["department_id"]
        assert work_item.shift_id == context["shift_id"]
        assert work_item.queue_status == WorkQueueStatusEnum.ASSIGNED
        assert work_item.due_date == now + due_offset
        assert assignment.employee_id == context["employee_id"]
        assert assignment.assignment_status == AssignmentStatusEnum.ASSIGNED
        assert schedule.last_run == now
        assert schedule.next_run == now + timedelta(hours=8)
        assert db.query(DepartmentWorkQueue).count() == 1


def test_due_shift_schedule_waits_for_checked_in_rostered_staff(workforce_session):
    session_local, context = workforce_session
    now = datetime.combine(date.today(), time(23, 30))

    with session_local() as db:
        task = TaskMaster(
            department_id=context["department_id"],
            task_name="Wait for check-in task",
            priority_category=PriorityEnum.HIGH,
            task_type=TaskTypeEnum.RECURRING,
            task_state=TaskStatusEnum.ACTIVE,
        )
        roster = ShiftRoster(
            employee_id=context["employee_id"],
            shift_id=context["shift_id"],
            work_date=date.today(),
            roster_status=RosterStatusEnum.SCHEDULED,
        )
        db.add_all([task, roster])
        db.flush()
        schedule = TaskSchedule(
            task_id=task.task_id,
            shift_id=context["shift_id"],
            schedule_name="Wait for check-in schedule",
            frequency_type=FrequencyTypeEnum.HOURS,
            frequency_value=8,
            next_run=now - timedelta(minutes=1),
            is_active=True,
        )
        db.add(schedule)
        db.commit()

        result = generate_scheduled_tasks(
            db,
            department_id=context["department_id"],
            shift_id=context["shift_id"],
            current_time=now,
            dispatch_events=False,
        )

        assert result["generated_count"] == 1
        pending_work = db.query(DepartmentWorkQueue).one()
        assert pending_work.queue_status == WorkQueueStatusEnum.PENDING_ASSIGNED
        assert db.query(OutboxEvent).filter(
            OutboxEvent.event_type == "RECURRING_TASK_GENERATED"
        ).count() == 0
        assert schedule.next_run == now + timedelta(hours=8)


def test_due_shift_schedule_skips_duplicate_unfinished_work(workforce_session):
    session_local, context = workforce_session
    now = datetime.combine(date.today(), time(23, 30))

    with session_local() as db:
        task = TaskMaster(
            department_id=context["department_id"],
            task_name="Existing unfinished task",
            priority_category=PriorityEnum.HIGH,
            task_type=TaskTypeEnum.RECURRING,
            task_state=TaskStatusEnum.ACTIVE,
        )
        roster = ShiftRoster(
            employee_id=context["employee_id"],
            shift_id=context["shift_id"],
            work_date=date.today(),
            roster_status=RosterStatusEnum.SCHEDULED,
        )
        db.add_all([task, roster])
        db.flush()
        existing_work = DepartmentWorkQueue(
            task_id=task.task_id,
            department_id=context["department_id"],
            shift_id=context["shift_id"],
            priority=PriorityEnum.HIGH,
            queue_status=WorkQueueStatusEnum.PENDING_ASSIGNED,
        )
        schedule = TaskSchedule(
            task_id=task.task_id,
            shift_id=context["shift_id"],
            schedule_name="Duplicate prevention schedule",
            frequency_type=FrequencyTypeEnum.HOURS,
            frequency_value=8,
            next_run=now - timedelta(minutes=1),
            is_active=True,
        )
        db.add_all([existing_work, schedule])
        db.commit()

        result = generate_scheduled_tasks(
            db,
            department_id=context["department_id"],
            shift_id=context["shift_id"],
            current_time=now,
            dispatch_events=False,
        )

        assert result["generated_count"] == 0
        assert result["skipped_count"] == 1
        assert "unfinished work already exists" in result["skipped"][0]["reason"]
        assert db.query(DepartmentWorkQueue).count() == 1
        assert schedule.last_run == now
        assert schedule.next_run == now + timedelta(hours=8)


def test_required_proof_blocks_direct_task_completion(workforce_session):
    session_local, context = workforce_session

    with session_local() as db:
        task = TaskMaster(
            department_id=context["department_id"],
            task_name="Proof-required task",
            priority_category=PriorityEnum.HIGH,
            task_type=TaskTypeEnum.RECURRING,
            task_state=TaskStatusEnum.ACTIVE,
            requires_proof=True,
        )
        db.add(task)
        db.flush()
        work = DepartmentWorkQueue(
            task_id=task.task_id,
            department_id=context["department_id"],
            priority=PriorityEnum.HIGH,
            queue_status=WorkQueueStatusEnum.ASSIGNED,
        )
        db.add(work)
        db.commit()

        with pytest.raises(AgentExecutionError, match="requires verified proof"):
            complete_work_item(work.work_id, db)

        assert work.queue_status == WorkQueueStatusEnum.ASSIGNED

        db.add(TaskProof(
            work_id=work.work_id,
            employee_id=context["employee_id"],
            proof_image_path="proofs/test-proof.jpg",
            verification_status=TaskProofStatusEnum.VERIFIED,
        ))
        db.commit()
        result = complete_work_item(work.work_id, db)
        assert result["new_status"] == WorkQueueStatusEnum.COMPLETED.value


def test_demo_proof_upload_verifies_and_allows_task_completion(
    workforce_session,
    monkeypatch,
    tmp_path,
):
    from app.services.task_proof_service import save_task_proof

    session_local, context = workforce_session
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with session_local() as db:
        task = TaskMaster(
            department_id=context["department_id"],
            task_name="Demo proof task",
            description="Upload proof for the assigned work item.",
            priority_category=PriorityEnum.HIGH,
            task_type=TaskTypeEnum.RECURRING,
            task_state=TaskStatusEnum.ACTIVE,
            requires_proof=True,
        )
        db.add(task)
        db.flush()
        work = DepartmentWorkQueue(
            task_id=task.task_id,
            department_id=context["department_id"],
            priority=PriorityEnum.HIGH,
            queue_status=WorkQueueStatusEnum.ASSIGNED,
        )
        db.add(work)
        db.flush()
        db.add(TaskAssignment(
            work_id=work.work_id,
            employee_id=context["employee_id"],
            assignment_status=AssignmentStatusEnum.ASSIGNED,
        ))
        db.commit()

        proof = save_task_proof(
            db=db,
            work_id=work.work_id,
            file_content=b"demo proof bytes",
            filename="proof.jpg",
        )
        assert proof["employee_id"] == context["employee_id"]
        assert db.query(OutboxEvent).filter(
            OutboxEvent.event_type == "TASK_PROOF_SUBMITTED",
        ).count() == 1

        assert process_pending_outbox_events(db) == 1
        trace = db.query(OrchestratorTrace).filter(
            OrchestratorTrace.event_type == HospitalEventEnum.TASK_PROOF_SUBMITTED.value,
        ).one()
        assert trace.execution_status == "SUCCESS", (
            f"{trace.error_message}: {trace.workflow_execution_json}"
        )
        db.refresh(work)
        verified_proof = db.query(TaskProof).filter(
            TaskProof.work_id == work.work_id,
        ).one()
        assert verified_proof.verification_status == TaskProofStatusEnum.VERIFIED
        assert verified_proof.ai_decision == "VERIFIED"
        assert "DEMO_MODE" in verified_proof.verification_rationale

        result = complete_work_item(work.work_id, db)
        assert result["new_status"] == WorkQueueStatusEnum.COMPLETED.value
        memory = db.get(WorkerMemory, context["employee_id"])
        assert memory is not None
        assert memory.pending_task == 0
        assert memory.total_task_completed == 1
        assert db.query(AgentActionLog).filter(
            AgentActionLog.action_type == "WORKFORCE_CHECK",
            AgentActionLog.execution_status == AgentActionStatusEnum.FAILED,
        ).count() == 0
