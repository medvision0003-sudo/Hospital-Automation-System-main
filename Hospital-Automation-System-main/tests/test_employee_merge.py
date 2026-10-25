from datetime import date, datetime, time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.dependencies import get_current_user
from app.database.base import Base
from app.database.connection import get_db
from app.main import app
from app.models.department import Department
from app.models.employee import Employee
from app.models.enums import (
    CheckinStatusEnum,
    EmploymentStatusEnum,
    GenderEnum,
    RosterStatusEnum,
    UserRoleEnum,
)
from app.models.shift import Shift
from app.models.shift_roster import ShiftRoster
from app.models.user import User
from app.models.worker_checkin import WorkerCheckin
from app.models.worker_memory import WorkerMemory


@pytest.fixture
def employee_merge_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine)

    def override_get_db():
        with session_local() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        role=UserRoleEnum.ADMIN
    )

    with session_local() as db:
        department = Department(department_name="Employee Merge Test")
        db.add(department)
        db.flush()
        target = Employee(
            department_id=department.department_id,
            name="Duplicate Nurse",
            role="Nurse",
            availability=EmploymentStatusEnum.ACTIVE,
            gender=GenderEnum.FEMALE,
        )
        source = Employee(
            department_id=department.department_id,
            name="duplicate nurse",
            role="Nurse",
            availability=EmploymentStatusEnum.ACTIVE,
            gender=GenderEnum.FEMALE,
        )
        morning = Shift(
            department_id=department.department_id,
            shift_name="Morning",
            start_time=time(7, 0),
            end_time=time(15, 0),
        )
        evening = Shift(
            department_id=department.department_id,
            shift_name="Evening",
            start_time=time(15, 0),
            end_time=time(23, 0),
        )
        db.add_all([target, source, morning, evening])
        db.flush()

        db.add_all([
            WorkerMemory(employee_id=target.employee_id, pending_task=1, total_task_completed=2),
            WorkerMemory(employee_id=source.employee_id, pending_task=3, total_task_completed=4),
            ShiftRoster(
                employee_id=target.employee_id,
                shift_id=morning.shift_id,
                work_date=date(2026, 7, 13),
                roster_status=RosterStatusEnum.COMPLETED,
            ),
            ShiftRoster(
                employee_id=source.employee_id,
                shift_id=evening.shift_id,
                work_date=date(2026, 7, 13),
                roster_status=RosterStatusEnum.COMPLETED,
            ),
            WorkerCheckin(
                device_id="TARGET-CHECKIN",
                employee_id=target.employee_id,
                checkin_time=datetime(2026, 7, 13, 7, 0),
                status=CheckinStatusEnum.CHECKED_IN,
            ),
            WorkerCheckin(
                device_id="SOURCE-CHECKIN",
                employee_id=source.employee_id,
                checkin_time=datetime(2026, 7, 13, 7, 1),
                status=CheckinStatusEnum.CHECKED_IN,
            ),
        ])
        db.commit()
        target_id = target.employee_id
        source_id = source.employee_id

    try:
        yield TestClient(app), session_local, target_id, source_id
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_merge_reassigns_rosters_and_consolidates_active_checkins(
    employee_merge_client,
):
    client, session_local, target_id, source_id = employee_merge_client

    response = client.post(f"/employees/{source_id}/merge-into/{target_id}")

    assert response.status_code == 200
    assert response.json()["reassigned_records"]["shift_scheduler"] == 1
    assert response.json()["reassigned_records"]["worker_checkin"] == 1

    with session_local() as db:
        assert db.query(Employee).filter(Employee.employee_id == source_id).first() is None
        rosters = db.query(ShiftRoster).filter(
            ShiftRoster.employee_id == target_id
        ).all()
        assert len(rosters) == 2
        checkins = db.query(WorkerCheckin).order_by(WorkerCheckin.checkin_time).all()
        assert len(checkins) == 2
        assert all(record.employee_id == target_id for record in checkins)
        assert checkins[0].status == CheckinStatusEnum.CHECKED_OUT
        assert checkins[0].checkout_time == checkins[1].checkin_time
        assert checkins[1].status == CheckinStatusEnum.CHECKED_IN
        memory = db.get(WorkerMemory, target_id)
        assert memory.pending_task == 4
        assert memory.total_task_completed == 6
        assert db.get(WorkerMemory, source_id) is None


def test_merge_rejects_different_names_and_accounts_are_transactional(
    employee_merge_client,
):
    client, session_local, target_id, source_id = employee_merge_client

    with session_local() as db:
        source = db.get(Employee, source_id)
        source.name = "Different Nurse"
        db.commit()

    response = client.post(f"/employees/{source_id}/merge-into/{target_id}")
    assert response.status_code == 409
    with session_local() as db:
        assert db.get(Employee, source_id) is not None

    with session_local() as db:
        source = db.get(Employee, source_id)
        source.name = "Duplicate Nurse"
        db.add_all([
            User(
                user_id=101,
                email="target@test.example",
                hashed_password="unused",
                role=UserRoleEnum.ADMIN,
                employee_id=target_id,
                is_active=True,
            ),
            User(
                user_id=102,
                email="source@test.example",
                hashed_password="unused",
                role=UserRoleEnum.SUPERVISOR,
                employee_id=source_id,
                is_active=True,
            ),
        ])
        db.commit()

    response = client.post(f"/employees/{source_id}/merge-into/{target_id}")
    assert response.status_code == 409
    with session_local() as db:
        assert db.get(Employee, source_id) is not None
