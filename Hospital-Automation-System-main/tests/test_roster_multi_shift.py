from datetime import date, time
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
from app.models.enums import EmploymentStatusEnum, GenderEnum, RosterStatusEnum, UserRoleEnum
from app.models.shift import Shift
from app.models.shift_roster import ShiftRoster


@pytest.fixture
def roster_client():
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
        department = Department(department_name="Roster Test")
        db.add(department)
        db.flush()
        employee = Employee(
            department_id=department.department_id,
            name="Roster Test Nurse",
            role="Nurse",
            availability=EmploymentStatusEnum.ACTIVE,
            gender=GenderEnum.FEMALE,
        )
        morning = Shift(
            department_id=department.department_id,
            shift_name="MORNING",
            start_time=time(7, 0),
            end_time=time(15, 0),
        )
        night = Shift(
            department_id=department.department_id,
            shift_name="NIGHT",
            start_time=time(23, 0),
            end_time=time(7, 0),
        )
        db.add_all([employee, morning, night])
        db.commit()
        employee_id = employee.employee_id
        morning_id = morning.shift_id
        night_id = night.shift_id

    try:
        yield TestClient(app), session_local, employee_id, morning_id, night_id
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_bulk_roster_saves_multiple_shifts_per_employee_date_idempotently(
    roster_client,
):
    client, session_local, employee_id, morning_id, night_id = roster_client
    work_date = date(2026, 7, 13).isoformat()
    items = [
        {
            "employee_id": employee_id,
            "shift_id": morning_id,
            "work_date": work_date,
            "roster_status": "COMPLETED",
        },
        {
            "employee_id": employee_id,
            "shift_id": night_id,
            "work_date": work_date,
            "roster_status": "COMPLETED",
        },
    ]

    response = client.post("/rosters/bulk", json={"items": items})
    assert response.status_code == 200
    assert response.json() == {"created": 2, "updated": 0, "deleted": 0}

    attendance_rosters = client.get(
        f"/rosters/range?start_date={work_date}&end_date={work_date}"
    )
    assert attendance_rosters.status_code == 200
    assert {roster["shift_id"] for roster in attendance_rosters.json()} == {
        morning_id,
        night_id,
    }

    repeated = client.post(
        "/rosters/bulk",
        json={
            "items": [
                {**items[0], "roster_status": "SCHEDULED"},
                items[1],
            ]
        },
    )
    assert repeated.status_code == 200
    assert repeated.json() == {"created": 0, "updated": 2, "deleted": 0}

    with session_local() as db:
        entries = db.query(ShiftRoster).order_by(ShiftRoster.shift_id).all()
        assert len(entries) == 2
        assert {entry.shift_id for entry in entries} == {morning_id, night_id}
        assert entries[0].roster_status == RosterStatusEnum.SCHEDULED
        assert entries[1].roster_status == RosterStatusEnum.COMPLETED

    cleared = client.post(
        "/rosters/bulk",
        json={
            "items": [
                {
                    "employee_id": employee_id,
                    "shift_id": None,
                    "work_date": work_date,
                }
            ]
        },
    )
    assert cleared.status_code == 200
    assert cleared.json() == {"created": 0, "updated": 0, "deleted": 2}
    with session_local() as db:
        assert db.query(ShiftRoster).count() == 0


def test_direct_roster_create_allows_different_shifts_but_rejects_exact_duplicate(
    roster_client,
):
    client, session_local, employee_id, morning_id, night_id = roster_client
    work_date = "2026-07-31"

    for shift_id in (morning_id, night_id):
        response = client.post(
            "/rosters/",
            json={
                "employee_id": employee_id,
                "shift_id": shift_id,
                "work_date": work_date,
                "roster_status": "COMPLETED",
            },
        )
        assert response.status_code == 201

    duplicate = client.post(
        "/rosters/",
        json={
            "employee_id": employee_id,
            "shift_id": morning_id,
            "work_date": work_date,
            "roster_status": "COMPLETED",
        },
    )
    assert duplicate.status_code == 409
    with session_local() as db:
        assert db.query(ShiftRoster).count() == 2
