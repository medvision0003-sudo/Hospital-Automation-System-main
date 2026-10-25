import io
from datetime import date, datetime

import openpyxl
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.core.dependencies import get_current_user
from app.database.base import Base
from app.database.connection import get_db
from app.main import app
from app.models.enums import UserRoleEnum
from app.models.automation_recommendation import AutomationRecommendation
from app.models.automation_rule import AutomationRule
from app.models.automation_rule_audit import AutomationRuleAudit
from app.models.automation_rule_execution import AutomationRuleExecution
from app.models.nursing_shift_log import NursingShiftLog
from app.models.user import User


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            NursingShiftLog.__table__,
            AutomationRecommendation.__table__,
            AutomationRule.__table__,
            AutomationRuleExecution.__table__,
            AutomationRuleAudit.__table__,
        ],
    )
    session_local = sessionmaker(bind=engine)

    def override_get_db():
        db = session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: User(
        user_id=1,
        email="admin@test.com",
        role=UserRoleEnum.ADMIN,
        is_active=True,
    )
    try:
        yield TestClient(app), session_local
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
        Base.metadata.drop_all(
            engine,
            tables=[
                AutomationRuleExecution.__table__,
                AutomationRuleAudit.__table__,
                AutomationRule.__table__,
                AutomationRecommendation.__table__,
                NursingShiftLog.__table__,
            ],
        )
        engine.dispose()


def workbook_bytes(include_required_headers=True):
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    headers = [
        "Timestamp",
        "1. Nurse Name",
        "2. Date",
        "3. Shift",
        "4. Ward / Area",
        "5. Total Patients Under Your Care (Enter a number)",
        "23. Pending Tasks for Next Shift (Specify details)",
    ]
    if not include_required_headers:
        headers.remove("4. Ward / Area")
    worksheet.append(headers)
    worksheet.append([
        datetime(2026, 10, 20, 8, 30),
        "Example Nurse",
        date(2026, 10, 20),
        "Morning",
        "Ward A",
        12,
        "Follow up",
    ][:len(headers)])
    stream = io.BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def test_import_shift_logs_and_skip_duplicates(client):
    test_client, session_local = client
    file_content = workbook_bytes()

    for _ in range(2):
        response = test_client.post(
            "/nursing-shift-logs/import",
            files={"file": ("responses.xlsx", file_content, "application/octet-stream")},
        )
        assert response.status_code == 200

    assert response.json() == {
        "total_processed": 1,
        "imported_count": 0,
        "skipped_count": 1,
    }
    with session_local() as db:
        record = db.query(NursingShiftLog).one()
        assert record.nurse_name == "Example Nurse"
        assert record.shift_date == date(2026, 10, 20)
        assert record.answers["5. Total Patients Under Your Care (Enter a number)"] == 12


def test_import_rejects_workbook_missing_required_header(client):
    test_client, session_local = client
    response = test_client.post(
        "/nursing-shift-logs/import",
        files={"file": ("responses.xlsx", workbook_bytes(False), "application/octet-stream")},
    )

    assert response.status_code == 400
    assert "4. Ward / Area" in response.json()["detail"]["missing_headers"]
    with session_local() as db:
        assert db.query(NursingShiftLog).count() == 0


def test_shift_report_creation_is_idempotent_and_analytics_are_historical(client):
    test_client, session_local = client
    app.dependency_overrides[get_current_user] = lambda: User(
        user_id=2,
        email="supervisor@test.com",
        role=UserRoleEnum.SUPERVISOR,
        is_active=True,
    )
    payload = {
        "nurse_name": "Report Nurse",
        "shift_date": "2026-10-20",
        "shift_name": "Morning",
        "ward_area": "Ward A",
        "answers": {
            "5. Total Patients Under Your Care (Enter a number)": "7",
            "16. Any Emergency During Shift?": "Yes",
            "11. Were All Medicines Given on Time?": "No",
            "20. Any Equipment Malfunction?": "Yes",
            "22. Was Proper Handover Given?": "No",
        },
    }
    first = test_client.post("/nursing-shift-logs/", json=payload)
    duplicate = test_client.post("/nursing-shift-logs/", json=payload)
    analytics = test_client.get("/nursing-shift-logs/analytics")

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert analytics.status_code == 200
    assert analytics.json()["total_records"] == 1
    assert analytics.json()["average_patients_per_shift"] == 7
    assert analytics.json()["emergency_occurrences"] == 1
    assert analytics.json()["medication_delay_rate_percent"] == 100
    assert analytics.json()["equipment_issue_rate_percent"] == 100
    assert analytics.json()["handover_issue_rate_percent"] == 100
    with session_local() as db:
        assert db.query(NursingShiftLog).count() == 1
