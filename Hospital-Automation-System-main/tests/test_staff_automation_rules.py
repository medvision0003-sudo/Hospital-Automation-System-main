from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.dependencies import get_current_user
from app.agents.pattern_learning_agent import _is_signal
from app.database.base import Base
from app.database.connection import get_db
from app.database.migrations import _migrate_staff_automation_rules
from app.main import app
from app.models.automation_rule import AutomationRule
from app.models.automation_rule_execution import AutomationRuleExecution
from app.models.department import Department
from app.models.employee import Employee
from app.models.enums import (
    EmploymentStatusEnum,
    GenderEnum,
    PriorityEnum,
    TaskStatusEnum,
    TaskTypeEnum,
    UserRoleEnum,
)
from app.models.nursing_shift_log import NursingShiftLog
from app.models.supervisor_task_request import SupervisorTaskRequest
from app.models.task_master import TaskMaster
from app.models.user import User
from app.services import staff_automation_rules


@pytest.fixture
def staff_automation_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine)
    active_user = {"user": None}

    def override_get_db():
        db = session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: active_user["user"]
    with session_local() as db:
        department = Department(department_name="Staff Automation Test")
        db.add(department)
        db.flush()
        employee = Employee(
            department_id=department.department_id,
            name="Supervisor Employee",
            role="Supervisor",
            availability=EmploymentStatusEnum.ACTIVE,
            gender=GenderEnum.FEMALE,
        )
        db.add(employee)
        db.flush()
        admin = User(
            user_id=1,
            email="automation-admin@test.com",
            hashed_password="unused",
            role=UserRoleEnum.ADMIN,
            is_active=True,
        )
        supervisor = User(
            user_id=2,
            employee_id=employee.employee_id,
            email="automation-supervisor@test.com",
            hashed_password="unused",
            role=UserRoleEnum.SUPERVISOR,
            is_active=True,
        )
        task = TaskMaster(
            task_id=1,
            task_state=TaskStatusEnum.ACTIVE,
            department_id=department.department_id,
            task_name="Inspect equipment report",
            description="Review operational equipment reports.",
            priority_category=PriorityEnum.MEDIUM,
            task_type=TaskTypeEnum.EVENT_TEMPLATE,
        )
        db.add_all([admin, supervisor, task])
        for index in range(10):
            answer = "Yes" if index < 3 else "No"
            db.add(
                NursingShiftLog(
                    source_hash=f"pattern-test-{index}",
                    submitted_at=datetime(2026, 1, 1) + timedelta(days=index),
                    nurse_name=f"Historical Nurse {index}",
                    shift_date=date(2026, 1, 1) + timedelta(days=index),
                    shift_name="Night",
                    ward_area="Ward A",
                    answers={"20. Any Equipment Malfunction?": answer},
                )
            )
        db.commit()
    try:
        yield TestClient(app), session_local, active_user
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_pattern_analysis_rule_approval_execution_and_effectiveness(
    staff_automation_client,
    monkeypatch,
):
    client, session_local, active_user = staff_automation_client
    active_user["user"] = User(
        user_id=1,
        email="automation-admin@test.com",
        role=UserRoleEnum.ADMIN,
        is_active=True,
    )

    analysis = client.post("/staff-automation/pattern-learning/analyze", json={})
    assert analysis.status_code == 200
    recommendations = analysis.json()["recommendations"]
    recommendation = next(
        item for item in recommendations
        if item["pattern_type"] == "equipment_malfunction"
        and item["ward_area"] == "Ward A"
        and item["shift_name"] == "Night"
    )
    assert recommendation["status"] == "PENDING_APPROVAL"
    assert recommendation["occurrences"] == 3
    assert recommendation["observations"] == 10
    assert recommendation["confidence"] > 0

    create_rule = client.post(
        f"/staff-automation/recommendations/{recommendation['recommendation_id']}/rules",
        json={"task_id": 1, "due_offset": "END_OF_DAY"},
    )
    assert create_rule.status_code == 201
    rule_id = create_rule.json()["rule_id"]
    assert create_rule.json()["status"] == "PENDING_APPROVAL"
    edited_rule = client.put(
        f"/staff-automation/rules/{rule_id}",
        json={"task_id": 1, "priority": "HIGH", "due_offset": "TWO_HOURS"},
    )
    assert edited_rule.status_code == 200
    assert edited_rule.json()["action_config"]["priority"] == "HIGH"
    assert edited_rule.json()["action_config"]["due_offset"] == "TWO_HOURS"

    blocked_approval = client.post(f"/staff-automation/rules/{rule_id}/approve", json={})
    assert blocked_approval.status_code == 400
    assert "linked to an employee" in blocked_approval.json()["detail"]

    active_user["user"] = User(
        user_id=2,
        employee_id=1,
        email="automation-supervisor@test.com",
        role=UserRoleEnum.SUPERVISOR,
        is_active=True,
    )
    approved = client.post(f"/staff-automation/rules/{rule_id}/approve", json={})
    assert approved.status_code == 200
    assert approved.json()["status"] == "ACTIVE"

    report_payload = {
        "nurse_name": "New Reporter",
        "shift_date": "2026-02-01",
        "shift_name": "Night",
        "ward_area": "Ward A",
        "answers": {"20. Any Equipment Malfunction?": "Yes"},
    }
    first_report = client.post("/nursing-shift-logs/", json=report_payload)
    assert first_report.status_code == 201
    assert first_report.json()["automation_executions"][0]["status"] == "SUCCEEDED"
    assert first_report.json()["automation_executions"][0]["supervisor_task_request_id"]

    with session_local() as db:
        report = db.query(NursingShiftLog).filter_by(nurse_name="New Reporter").one()
        repeated = staff_automation_rules.execute_rules_for_report(db, report)
        assert len(repeated) == 1
        assert db.query(AutomationRuleExecution).filter_by(rule_id=rule_id).count() == 1
        assert db.query(SupervisorTaskRequest).count() == 1

    def fail_request(*_args, **_kwargs):
        raise RuntimeError("Existing supervisor workflow unavailable.")

    monkeypatch.setattr(staff_automation_rules, "create_supervisor_request", fail_request)
    report_payload["shift_date"] = "2026-02-02"
    failed_report = client.post("/nursing-shift-logs/", json=report_payload)
    assert failed_report.status_code == 201
    assert failed_report.json()["automation_executions"][0]["status"] == "FAILED"
    assert "workflow unavailable" in failed_report.json()["automation_executions"][0]["error_message"]

    effectiveness = client.get(f"/staff-automation/rules/{rule_id}/effectiveness")
    assert effectiveness.status_code == 200
    assert effectiveness.json()["total_executions"] == 2
    assert effectiveness.json()["succeeded"] == 1
    assert effectiveness.json()["failed"] == 1

    disabled = client.post(f"/staff-automation/rules/{rule_id}/disable", json={})
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "DISABLED"
    audit = client.get(f"/staff-automation/audit?rule_id={rule_id}")
    assert audit.status_code == 200
    assert {entry["action"] for entry in audit.json()} >= {
        "RULE_CREATED_PENDING_APPROVAL",
        "RULE_APPROVED",
        "RULE_ACTIVATED",
        "RULE_DISABLED",
    }

    global_recommendation = next(
        item for item in recommendations
        if item["pattern_type"] == "equipment_malfunction"
        and item["ward_area"] is None
        and item["shift_name"] is None
    )
    global_rule_response = client.post(
        f"/staff-automation/recommendations/{global_recommendation['recommendation_id']}/rules",
        json={"task_id": 1},
    )
    assert global_rule_response.status_code == 201
    global_rule_id = global_rule_response.json()["rule_id"]
    approved_global = client.post(
        f"/staff-automation/rules/{global_rule_id}/approve",
        json={},
    )
    assert approved_global.status_code == 200
    with session_local() as db:
        expired_rule = db.query(AutomationRule).filter_by(rule_id=global_rule_id).one()
        expired_rule.expires_at = datetime.now() - timedelta(minutes=1)
        db.commit()
    expired = client.post("/staff-automation/rules/expire", json={})
    assert expired.status_code == 200
    assert expired.json()["expired"] == 1
    with session_local() as db:
        assert db.query(AutomationRule).filter_by(rule_id=global_rule_id).one().status == "EXPIRED"


def test_pattern_learning_enforces_recurrence_sample_minimum(staff_automation_client):
    client, session_local, active_user = staff_automation_client
    active_user["user"] = User(
        user_id=1,
        email="automation-admin@test.com",
        role=UserRoleEnum.ADMIN,
        is_active=True,
    )
    with session_local() as db:
        db.query(NursingShiftLog).filter(NursingShiftLog.log_id >= 9).delete()
        db.commit()

    analysis = client.post("/staff-automation/pattern-learning/analyze", json={})
    assert analysis.status_code == 200
    assert analysis.json()["reports_analyzed"] == 8
    assert analysis.json()["recommendations"] == []


def test_pattern_signal_parsing_respects_negative_answers():
    assert _is_signal("medication_delay", "No")
    assert not _is_signal("medication_delay", "No delay")
    assert not _is_signal("equipment_malfunction", "No malfunction")
    assert _is_signal("equipment_malfunction", "Not working")
    assert not _is_signal("handover_issue", "Yes, proper handover")
    assert _is_signal("handover_issue", "No")
    assert not _is_signal("emergency_reported", "No")


def test_existing_rule_schema_gets_additive_approval_identity_column():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE employee (employee_id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE automation_rule (rule_id INTEGER PRIMARY KEY)"))

    _migrate_staff_automation_rules(engine, inspect(engine))
    _migrate_staff_automation_rules(engine, inspect(engine))

    columns = {column["name"] for column in inspect(engine).get_columns("automation_rule")}
    assert "approved_employee_id" in columns
    engine.dispose()
