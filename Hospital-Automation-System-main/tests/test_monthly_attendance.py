from datetime import datetime
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
    UserRoleEnum,
)
from app.models.worker_checkin import WorkerCheckin


@pytest.fixture
def monthly_attendance_client():
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
        role=UserRoleEnum.ADMIN,
        department_id=None,
    )
    with session_local() as db:
        nursing = Department(department_name="Monthly Nursing")
        pharmacy = Department(department_name="Monthly Pharmacy")
        db.add_all([nursing, pharmacy])
        db.flush()
        nurse = Employee(
            department_id=nursing.department_id,
            name="Monthly Nurse",
            role="Nurse",
            availability=EmploymentStatusEnum.ACTIVE,
            gender=GenderEnum.FEMALE,
        )
        pharmacist = Employee(
            department_id=pharmacy.department_id,
            name="Monthly Pharmacist",
            role="Pharmacist",
            availability=EmploymentStatusEnum.ACTIVE,
            gender=GenderEnum.MALE,
        )
        db.add_all([nurse, pharmacist])
        db.flush()
        db.add_all([
            WorkerCheckin(
                device_id="MONTHLY-NURSE",
                employee_id=nurse.employee_id,
                checkin_time=datetime(2026, 10, 1, 7, 1),
                status=CheckinStatusEnum.CHECKED_IN,
            ),
            WorkerCheckin(
                device_id="MONTHLY-PHARMACIST",
                employee_id=pharmacist.employee_id,
                checkin_time=datetime(2026, 10, 31, 8, 2),
                status=CheckinStatusEnum.CHECKED_IN,
            ),
            WorkerCheckin(
                device_id="MONTHLY-OUTSIDE",
                employee_id=nurse.employee_id,
                checkin_time=datetime(2026, 11, 1, 8, 3),
                status=CheckinStatusEnum.CHECKED_IN,
            ),
        ])
        db.commit()
        nursing_id = nursing.department_id
        pharmacy_id = pharmacy.department_id
        nurse_id = nurse.employee_id
        pharmacist_id = pharmacist.employee_id

    try:
        yield TestClient(app), nursing_id, pharmacy_id, nurse_id, pharmacist_id
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_monthly_checkins_are_bounded_and_department_filterable(monthly_attendance_client):
    client, nursing_id, pharmacy_id, nurse_id, pharmacist_id = monthly_attendance_client

    monthly = client.get(
        "/checkins/range",
        params={"start_date": "2026-10-01", "end_date": "2026-10-31"},
    )
    assert monthly.status_code == 200
    assert len(monthly.json()) == 2
    assert {row["employee_id"] for row in monthly.json()} == {nurse_id, pharmacist_id}

    department = client.get(
        "/checkins/range",
        params={
            "start_date": "2026-10-01",
            "end_date": "2026-10-31",
            "department_id": pharmacy_id,
        },
    )
    assert department.status_code == 200
    assert len(department.json()) == 1
    assert department.json()[0]["employee_id"] == pharmacist_id
    assert nursing_id != pharmacy_id


def test_monthly_checkins_reject_invalid_or_oversized_range(monthly_attendance_client):
    client, *_ = monthly_attendance_client

    reversed_range = client.get(
        "/checkins/range",
        params={"start_date": "2026-10-31", "end_date": "2026-10-01"},
    )
    assert reversed_range.status_code == 400

    oversized_range = client.get(
        "/checkins/range",
        params={"start_date": "2026-10-01", "end_date": "2026-11-02"},
    )
    assert oversized_range.status_code == 400


def test_annual_checkins_return_only_requested_calendar_year(monthly_attendance_client):
    client, _, _, nurse_id, pharmacist_id = monthly_attendance_client

    response = client.get("/checkins/year", params={"year": 2026})

    assert response.status_code == 200
    assert {row["employee_id"] for row in response.json()} == {nurse_id, pharmacist_id}
    assert all(row["checkin_time"].startswith("2026-") for row in response.json())


def test_supervisor_monthly_checkins_are_department_scoped(monthly_attendance_client):
    client, nursing_id, pharmacy_id, nurse_id, _ = monthly_attendance_client
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        role=UserRoleEnum.SUPERVISOR,
        department_id=nursing_id,
    )

    scoped = client.get(
        "/checkins/range",
        params={"start_date": "2026-10-01", "end_date": "2026-10-31"},
    )
    assert scoped.status_code == 200
    assert len(scoped.json()) == 1
    assert scoped.json()[0]["employee_id"] == nurse_id

    other_department = client.get(
        "/checkins/range",
        params={
            "start_date": "2026-10-01",
            "end_date": "2026-10-31",
            "department_id": pharmacy_id,
        },
    )
    assert other_department.status_code == 404
