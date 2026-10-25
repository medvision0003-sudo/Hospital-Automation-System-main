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
    HospitalEventEnum,
    UserRoleEnum,
)
from app.models.worker_checkin import WorkerCheckin
from app.routes.workflow import device_attendance
from app.routes.workflow import hospital_events
from app.routes.admin import checkins as admin_checkins


@pytest.fixture
def attendance_client():
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
        department = Department(department_name="Attendance Test")
        db.add(department)
        db.flush()
        employee = Employee(
            department_id=department.department_id,
            name="Attendance Worker",
            role="Nurse",
            availability=EmploymentStatusEnum.ACTIVE,
            gender=GenderEnum.FEMALE,
        )
        db.add(employee)
        db.commit()
        employee_id = employee.employee_id

    try:
        yield TestClient(app), session_local, employee_id
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_registered_device_authenticates_checkin_and_checkout(
    attendance_client,
    monkeypatch,
):
    client, session_local, employee_id = attendance_client
    registration = client.post(
        "/admin/attendance-devices/",
        json={"device_id": "FRONT-DESK-01", "employee_id": employee_id},
    )
    assert registration.status_code == 201
    token = registration.json()["device_token"]

    event = {
        "device_id": "FRONT-DESK-01",
        "employee_id": employee_id,
        "event": "CHECK_IN",
        "occurred_at": datetime.now().isoformat(),
    }
    assert client.post("/device-attendance/event", json=event).status_code == 401
    assert client.post(
        "/device-attendance/event",
        json={**event, "employee_id": employee_id + 1},
        headers={"X-Device-Token": token},
    ).status_code == 403

    published_events = []

    def publish_event(event_type, payload, db):
        published_events.append((event_type, payload))
        if event_type == HospitalEventEnum.WORKER_CHECKED_OUT:
            record = db.query(WorkerCheckin).filter(
                WorkerCheckin.employee_id == payload["employee_id"]
            ).one()
            record.status = CheckinStatusEnum.CHECKED_OUT
            record.checkout_time = datetime.fromisoformat(payload["occurred_at"])
            db.flush()
            return {"workflow_id": "checkout-workflow"}

        db.add(
            WorkerCheckin(
                device_id=payload["device_id"],
                checkin_time=datetime.fromisoformat(payload["occurred_at"]),
                employee_id=payload["employee_id"],
                status=CheckinStatusEnum.CHECKED_IN,
            )
        )
        db.flush()
        return {"workflow_id": "test-workflow"}

    monkeypatch.setattr(device_attendance, "publish_event", publish_event)
    headers = {"X-Device-Token": token}
    checked_in = client.post("/device-attendance/event", json=event, headers=headers)
    assert checked_in.status_code == 200
    assert checked_in.json()["result"]["workflow_id"] == "test-workflow"
    assert client.post("/device-attendance/event", json=event, headers=headers).status_code == 409

    checked_out = client.post(
        "/device-attendance/event",
        json={**event, "event": "CHECK_OUT"},
        headers=headers,
    )
    assert checked_out.status_code == 200
    with session_local() as db:
        record = db.query(WorkerCheckin).one()
        assert record.status == CheckinStatusEnum.CHECKED_OUT
        assert record.checkout_time is not None
        assert [event_type for event_type, _ in published_events] == [
            HospitalEventEnum.WORKER_CHECKED_IN,
            HospitalEventEnum.WORKER_CHECKED_OUT,
        ]
        assert all(
            payload["trigger_source"] == "ATTENDANCE_DEVICE"
            for _, payload in published_events
        )

    assert client.delete("/admin/attendance-devices/FRONT-DESK-01").status_code == 204
    assert client.post("/device-attendance/event", json=event, headers=headers).status_code == 401


@pytest.mark.parametrize("event_type", ["WORKER_CHECKED_IN", "WORKER_CHECKED_OUT"])
def test_event_gateway_requires_manual_override_for_attendance(
    attendance_client,
    monkeypatch,
    event_type,
):
    client, _, employee_id = attendance_client
    published = []

    def publish_event(event, payload, db):
        published.append((event, payload))
        return {"status": "SUCCESS"}

    monkeypatch.setattr(hospital_events, "publish_event", publish_event)
    body = {
        "event_type": event_type,
        "payload": {"employee_id": employee_id},
    }

    rejected = client.post("/events/?sync=true", json=body)
    assert rejected.status_code == 400
    assert published == []

    accepted = client.post(
        "/events/?sync=true",
        json={
            **body,
            "payload": {**body["payload"], "trigger_source": "MANUAL_OVERRIDE"},
        },
    )
    assert accepted.status_code == 200
    assert published[0][0] == HospitalEventEnum(event_type)
    assert published[0][1]["trigger_source"] == "MANUAL_OVERRIDE"


def test_legacy_admin_checkin_api_uses_manual_event_workflow(
    attendance_client,
    monkeypatch,
):
    client, session_local, employee_id = attendance_client
    occurred_at = datetime.now().replace(microsecond=0)
    published = []

    def publish_event(event_type, payload, db):
        published.append((event_type, payload))
        db.add(WorkerCheckin(
            device_id="MANUAL_OVERRIDE_TEST",
            checkin_time=occurred_at,
            employee_id=employee_id,
            status=CheckinStatusEnum.CHECKED_IN,
        ))
        db.commit()
        return {"status": "SUCCESS"}

    monkeypatch.setattr(admin_checkins, "publish_event", publish_event)
    response = client.post(
        "/checkins",
        json={
            "device_id": "OLD_MANUAL_FORM",
            "employee_id": employee_id,
            "checkin_time": occurred_at.isoformat(),
        },
    )

    assert response.status_code == 201
    assert published[0][0] == HospitalEventEnum.WORKER_CHECKED_IN
    assert published[0][1]["trigger_source"] == "MANUAL_OVERRIDE"
    with session_local() as db:
        record = db.query(WorkerCheckin).one()
        assert record.device_id == "MANUAL_OVERRIDE_TEST"


def test_admin_cannot_directly_change_device_attendance(attendance_client):
    client, session_local, employee_id = attendance_client
    checkin_time = datetime.now().replace(microsecond=0)
    with session_local() as db:
        db.add(WorkerCheckin(
            device_id="REGISTERED_DEVICE",
            checkin_time=checkin_time,
            employee_id=employee_id,
            status=CheckinStatusEnum.CHECKED_IN,
        ))
        db.commit()

    response = client.put(
        "/checkins",
        params={
            "device_id": "REGISTERED_DEVICE",
            "checkin_time": checkin_time.isoformat(),
        },
        json={"status": "CHECKED_OUT", "checkout_time": datetime.now().isoformat()},
    )

    assert response.status_code == 400
    with session_local() as db:
        record = db.query(WorkerCheckin).one()
        assert record.status == CheckinStatusEnum.CHECKED_IN
        assert record.checkout_time is None
