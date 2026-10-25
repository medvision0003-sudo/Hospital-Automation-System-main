from datetime import date, datetime, time, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.models.agent_action_log import AgentActionLog
from app.models.department import Department
from app.models.department_work_queue import DepartmentWorkQueue
from app.models.employee import Employee
from app.models.event_log import EventLog
from app.models.enums import (
    AssignmentStatusEnum,
    EmploymentStatusEnum,
    FrequencyTypeEnum,
    GenderEnum,
    PriorityEnum,
    RosterStatusEnum,
    TaskStatusEnum,
    TaskTypeEnum,
    WorkQueueStatusEnum,
)
from app.models.shift import Shift
from app.models.shift_roster import ShiftRoster
from app.models.task_assignment import TaskAssignment
from app.models.task_master import TaskMaster
from app.models.task_schedule import TaskSchedule
from app.models.orchestrator_trace import OrchestratorTrace
from app.services.staff_task_library import TASK_LIBRARY, seed_staff_task_library


def _make_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)


def test_seed_staff_task_library_is_idempotent_and_role_constrained():
    engine, session_local = _make_session()
    try:
        with session_local() as db:
            first = seed_staff_task_library(db)
            second = seed_staff_task_library(db)

            templates = db.query(TaskMaster).all()
            schedules = db.query(TaskSchedule).all()

            assert first["templates_created"] == len(TASK_LIBRARY)
            assert first["schedules_created"] == len(TASK_LIBRARY)
            assert second["templates_created"] == 0
            assert second["schedules_created"] == 0
            assert len(templates) == len(TASK_LIBRARY)
            assert len(schedules) == len(TASK_LIBRARY)
            assert {
                "Vital Signs Monitoring",
                "Patient Medication Administration",
                "Patient Care Plan Update",
                "Nursing Documentation",
                "Infection Control Round",
                "Patient Bedside Check",
                "IV/Fluid Monitoring",
                "Shift Handover Documentation",
                "Ward Inspection",
                "Bed Availability Check",
                "Equipment Readiness Check",
                "Patient Area Safety Check",
                "Infection Control Inspection",
                "Medical Supply Check",
                "Medication Stock Verification",
                "Expiry Date Check",
                "Controlled Medication Count",
                "Prescription Queue Review",
                "Medication Storage Inspection",
                "Sample Collection Verification",
                "Sample Label Validation",
                "Pending Sample Review",
                "Lab Safety Checklist",
                "Patient Registration Queue",
                "Appointment Verification",
                "Insurance/Document Verification",
                "Patient Help Desk Follow-up",
                "Patient Queue Coordination",
                "Ward Cleaning Verification",
                "Sanitization Checklist",
                "Waste Segregation Check",
                "High-touch Surface Cleaning",
                "Linen and Supply Restock Check",
            } <= {task.task_name for task in templates}
            assert all(
                5 <= sum(task.department_id == department_id for task in templates) <= 8
                for department_id in {task.department_id for task in templates}
            )
            assert all(
                task.required_role
                and task.required_skill
                and task.estimated_time
                and task.suggested_start_time
                and task.due_time
                and task.requires_proof
                and task.task_state == TaskStatusEnum.ACTIVE
                for task in templates
            )
            assert all(
                schedule.is_active
                and schedule.frequency_type == FrequencyTypeEnum.DAYS
                for schedule in schedules
            )

            inactive_template = templates[0]
            inactive_template.task_state = TaskStatusEnum.INACTIVE
            inactive_schedule = next(
                schedule
                for schedule in schedules
                if schedule.task_id == inactive_template.task_id
            )
            inactive_schedule.is_active = False
            db.commit()
            seed_staff_task_library(db)
            db.refresh(inactive_template)
            db.refresh(inactive_schedule)
            assert inactive_template.task_state == TaskStatusEnum.INACTIVE
            assert inactive_schedule.is_active is False
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_seed_deactivates_legacy_demo_tasks_and_cancels_only_open_work():
    engine, session_local = _make_session()
    try:
        with session_local() as db:
            department = Department(department_name="Ward")
            db.add(department)
            db.flush()
            employee = Employee(
                department_id=department.department_id,
                name="Ward staff",
                role="WARD_STAFF",
                availability=EmploymentStatusEnum.ACTIVE,
                gender=GenderEnum.FEMALE,
            )
            legacy_task = TaskMaster(
                department_id=department.department_id,
                task_name="DAILY WARD SANITIZATION",
                description="Old generic demo task",
                priority_category=PriorityEnum.HIGH,
                estimated_time=30,
                task_type=TaskTypeEnum.RECURRING,
                task_state=TaskStatusEnum.ACTIVE,
            )
            db.add_all([employee, legacy_task])
            db.flush()
            schedule = TaskSchedule(
                task_id=legacy_task.task_id,
                schedule_name="Legacy daily schedule",
                frequency_type=FrequencyTypeEnum.DAYS,
                frequency_value=1,
                next_run=datetime.now(),
                is_active=True,
            )
            pending_work = DepartmentWorkQueue(
                task_id=legacy_task.task_id,
                department_id=department.department_id,
                priority=PriorityEnum.HIGH,
                queue_status=WorkQueueStatusEnum.ASSIGNED,
            )
            completed_work = DepartmentWorkQueue(
                task_id=legacy_task.task_id,
                department_id=department.department_id,
                priority=PriorityEnum.HIGH,
                queue_status=WorkQueueStatusEnum.COMPLETED,
            )
            db.add_all([schedule, pending_work, completed_work])
            db.flush()
            active_assignment = TaskAssignment(
                work_id=pending_work.work_id,
                employee_id=employee.employee_id,
                assignment_status=AssignmentStatusEnum.ASSIGNED,
            )
            completed_assignment = TaskAssignment(
                work_id=completed_work.work_id,
                employee_id=employee.employee_id,
                assignment_status=AssignmentStatusEnum.COMPLETED,
            )
            db.add_all([active_assignment, completed_assignment])
            db.commit()

            result = seed_staff_task_library(db)
            db.refresh(legacy_task)
            db.refresh(schedule)
            db.refresh(pending_work)
            db.refresh(completed_work)
            db.refresh(active_assignment)
            db.refresh(completed_assignment)

            assert result["obsolete_work_cancelled"] == 1
            assert legacy_task.task_state == TaskStatusEnum.INACTIVE
            assert schedule.is_active is False
            assert pending_work.queue_status == WorkQueueStatusEnum.CANCELLED
            assert active_assignment.assignment_status == AssignmentStatusEnum.CANCELLED
            assert completed_work.queue_status == WorkQueueStatusEnum.COMPLETED
            assert completed_assignment.assignment_status == AssignmentStatusEnum.COMPLETED
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_catalog_task_due_time_becomes_the_generated_work_due_date():
    from app.services.recurring_task_scheduler import _task_due_date

    task = TaskMaster(
        task_name="Task with due time",
        task_type=TaskTypeEnum.RECURRING,
        priority_category=PriorityEnum.MEDIUM,
        due_time=time(12, 30),
    )
    now = datetime(2025, 4, 1, 10, 0)

    assert _task_due_date(task, None, now) == datetime(2025, 4, 1, 12, 30)


def test_seeded_task_template_generates_work_for_matching_department_roster():
    from app.services.recurring_task_scheduler import generate_scheduled_tasks

    engine, session_local = _make_session()
    try:
        with session_local() as db:
            seed_staff_task_library(db)
            department = db.query(Department).filter(
                Department.department_name == "Nursing"
            ).one()
            employee = Employee(
                department_id=department.department_id,
                name="Rostered nurse",
                role="NURSE",
                availability=EmploymentStatusEnum.ACTIVE,
                gender=GenderEnum.FEMALE,
                skill="VITAL_SIGNS",
            )
            shift = Shift(
                department_id=department.department_id,
                shift_name="Day shift",
                start_time=time(0, 0),
                end_time=time(23, 59, 59),
            )
            db.add_all([employee, shift])
            db.flush()
            db.add(ShiftRoster(
                employee_id=employee.employee_id,
                shift_id=shift.shift_id,
                work_date=date.today(),
                roster_status=RosterStatusEnum.SCHEDULED,
            ))
            now = datetime.now()
            for nursing_task in db.query(TaskMaster).filter(
                TaskMaster.department_id == department.department_id
            ).all():
                task_schedule = db.query(TaskSchedule).filter(
                    TaskSchedule.task_id == nursing_task.task_id
                ).one()
                task_schedule.next_run = now + timedelta(days=1)
            task = db.query(TaskMaster).filter(
                TaskMaster.task_name == "Vital Signs Monitoring"
            ).one()
            schedule = db.query(TaskSchedule).filter(
                TaskSchedule.task_id == task.task_id
            ).one()
            schedule.next_run = now - timedelta(minutes=1)
            db.commit()

            result = generate_scheduled_tasks(
                db,
                department_id=department.department_id,
                shift_id=shift.shift_id,
                current_time=now,
                dispatch_events=False,
            )
            work = db.query(DepartmentWorkQueue).filter(
                DepartmentWorkQueue.task_id == task.task_id
            ).one()

            assert result["generated_count"] == 1
            assert work.due_date == datetime.combine(now.date(), time(8, 0))
            assert work.shift_id == shift.shift_id
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_checkin_automatically_assigns_seeded_task_to_matching_employee(monkeypatch):
    from app.agents import assignment_agent
    from app.agents.event_agent import publish_event
    from app.models.enums import HospitalEventEnum

    engine, session_local = _make_session()
    try:
        with session_local() as db:
            seed_staff_task_library(db)
            department = db.query(Department).filter(
                Department.department_name == "Nursing"
            ).one()
            now = datetime.now().replace(microsecond=0)
            employee = Employee(
                department_id=department.department_id,
                name="Qualified Nurse",
                role="NURSE",
                availability=EmploymentStatusEnum.ACTIVE,
                gender=GenderEnum.FEMALE,
                skill=",".join(
                    task["required_skill"] for task in TASK_LIBRARY
                    if task["department"] == "Nursing"
                ),
            )
            shift = Shift(
                department_id=department.department_id,
                shift_name="Automation test shift",
                start_time=time(0, 0),
                end_time=time(23, 59, 59),
            )
            db.add_all([employee, shift])
            db.flush()
            roster = ShiftRoster(
                employee_id=employee.employee_id,
                shift_id=shift.shift_id,
                work_date=now.date(),
                roster_status=RosterStatusEnum.SCHEDULED,
            )
            db.add(roster)
            db.flush()

            tasks = db.query(TaskMaster).filter(
                TaskMaster.department_id == department.department_id
            ).all()
            target_task = next(
                task for task in tasks
                if task.task_name == "Vital Signs Monitoring"
            )
            for task in tasks:
                schedule = db.query(TaskSchedule).filter(
                    TaskSchedule.task_id == task.task_id
                ).one()
                schedule.next_run = now + timedelta(days=1)
            target_schedule = db.query(TaskSchedule).filter(
                TaskSchedule.task_id == target_task.task_id
            ).one()
            target_schedule.next_run = now - timedelta(minutes=1)
            db.commit()

            monkeypatch.setattr(
                assignment_agent,
                "_select_candidate_with_reasoning",
                lambda **kwargs: (_ for _ in ()).throw(
                    RuntimeError("test uses deterministic skill-eligibility fallback")
                ),
            )
            result = publish_event(
                HospitalEventEnum.WORKER_CHECKED_IN,
                {
                    "employee_id": employee.employee_id,
                    "occurred_at": now.isoformat(),
                    "trigger_source": "MANUAL_OVERRIDE",
                },
                db,
            )

            assert result["status"] == "SUCCESS", result.get("reason")
            work = db.query(DepartmentWorkQueue).filter(
                DepartmentWorkQueue.task_id == target_task.task_id
            ).one()
            assignment = db.query(TaskAssignment).filter(
                TaskAssignment.work_id == work.work_id
            ).one()
            generated_work = db.query(DepartmentWorkQueue).filter(
                DepartmentWorkQueue.department_id == department.department_id
            ).all()
            assert assignment.employee_id == employee.employee_id
            assert assignment.assignment_status == AssignmentStatusEnum.ASSIGNED
            assert work.queue_status == WorkQueueStatusEnum.ASSIGNED
            assert target_task.required_role == employee.role
            assert target_task.required_skill in employee.skill.split(",")
            assert len(generated_work) == 8
            assert all(item.shift_id == shift.shift_id for item in generated_work)
            assert all(
                db.query(TaskAssignment).filter(
                    TaskAssignment.work_id == item.work_id,
                    TaskAssignment.employee_id == employee.employee_id,
                    TaskAssignment.assignment_status == AssignmentStatusEnum.ASSIGNED,
                ).count() == 1
                for item in generated_work
            )
            checkin_event = db.query(EventLog).filter(
                EventLog.event_log == HospitalEventEnum.WORKER_CHECKED_IN.value,
                EventLog.employee_id == employee.employee_id,
            ).one()
            trace = db.query(OrchestratorTrace).filter(
                OrchestratorTrace.event_type == HospitalEventEnum.WORKER_CHECKED_IN.value,
            ).one()
            assert trace.execution_status == "SUCCESS"
            assert db.query(AgentActionLog).filter(
                AgentActionLog.action_type == "WORKFORCE_CHECK",
                AgentActionLog.event_id == checkin_event.event_id,
            ).count() == 1
            assert db.query(AgentActionLog).filter(
                AgentActionLog.action_type == "CREATE_WORK_ITEM",
                AgentActionLog.workflow_id == trace.workflow_id,
                AgentActionLog.event_id.isnot(None),
            ).count() == 8
            assert db.query(AgentActionLog).filter(
                AgentActionLog.action_type == "ASSIGN_TASK",
                AgentActionLog.workflow_id == trace.workflow_id,
                AgentActionLog.event_id.isnot(None),
            ).count() == 8
            assert db.query(AgentActionLog).filter(
                AgentActionLog.action_type == "WORKFORCE_CHECK",
                AgentActionLog.event_id == checkin_event.event_id,
                AgentActionLog.workflow_id == trace.workflow_id,
            ).count() == 1

            duplicate = publish_event(
                HospitalEventEnum.WORKER_CHECKED_IN,
                {
                    "employee_id": employee.employee_id,
                    "occurred_at": now.isoformat(),
                    "trigger_source": "MANUAL_OVERRIDE",
                },
                db,
            )
            assert duplicate["status"] == "SUCCESS"
            assert db.query(DepartmentWorkQueue).count() == 8
            assert db.query(TaskAssignment).count() == 8
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
