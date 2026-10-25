from datetime import date, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.models.agent_action_log import AgentActionLog
from app.models.department_work_queue import DepartmentWorkQueue
from app.models.employee import Employee
from app.models.enums import RosterStatusEnum
from app.models.shift import Shift
from app.models.shift_roster import ShiftRoster
from app.models.task_assignment import TaskAssignment
from app.models.worker_checkin import WorkerCheckin
from app.services.demo_staff_data import (
    demo_staff_data_enabled,
    seed_demo_staff_data,
)
from app.services.staff_task_library import seed_staff_task_library


def test_demo_staff_seed_creates_weekly_eligible_rosters_idempotently():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine)
    start_date = date.today()

    try:
        with session_local() as db:
            seed_staff_task_library(db)

            initial = seed_demo_staff_data(db, start_date)
            assert initial == {
                "employees_created": 56,
                "employees_available": 56,
                "rosters_created": 392,
            }

            employees = db.query(Employee).all()
            assert len(employees) == 56
            assert len({employee.name for employee in employees}) == 56
            assert all(employee.name.startswith("Demo ") for employee in employees)
            assert all(employee.role and employee.skill for employee in employees)
            for employee in employees:
                compatible_tasks = [
                    task for task in employee.department.tasks
                    if task.department_id == employee.department_id
                    and task.required_role == employee.role
                ]
                assert compatible_tasks
                assert {
                    task.required_skill for task in compatible_tasks
                    if task.required_skill
                } <= set(employee.skill.split(","))
                assert any(
                    task.department_id == employee.department_id
                    and task.required_role == employee.role
                    and task.required_skill in employee.skill.split(",")
                    for task in employee.department.tasks
                )
                today_roster = db.query(ShiftRoster).filter(
                    ShiftRoster.employee_id == employee.employee_id,
                    ShiftRoster.work_date == start_date,
                ).one()
                today_shift = db.query(Shift).filter(
                    Shift.shift_id == today_roster.shift_id
                ).one()
                shift_start = datetime.combine(start_date, today_shift.start_time)
                shift_end = datetime.combine(start_date, today_shift.end_time)
                if shift_end <= shift_start:
                    shift_end += timedelta(days=1)
                assert shift_start <= datetime.now() < shift_end
                assert today_roster.roster_status == RosterStatusEnum.SCHEDULED
            assert db.query(ShiftRoster).count() == 392

            repeated = seed_demo_staff_data(db, start_date)
            assert repeated == {
                "employees_created": 0,
                "employees_available": 56,
                "rosters_created": 0,
            }
            assert db.query(Employee).count() == 56
            assert db.query(ShiftRoster).count() == 392
            assert db.query(WorkerCheckin).count() == 0
            assert db.query(DepartmentWorkQueue).count() == 0
            assert db.query(TaskAssignment).count() == 0
            assert db.query(AgentActionLog).count() == 0
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_demo_staff_seed_defaults_to_development_and_never_production(monkeypatch):
    monkeypatch.delenv("DEMO_DATA_ENABLED", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    assert demo_staff_data_enabled()

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DEMO_DATA_ENABLED", "true")
    assert not demo_staff_data_enabled()

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_DATA_ENABLED", "false")
    assert not demo_staff_data_enabled()
