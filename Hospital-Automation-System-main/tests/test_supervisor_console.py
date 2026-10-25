from datetime import datetime, timedelta

from fastapi.testclient import TestClient
import pytest
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
    EmploymentStatusEnum,
    GenderEnum,
    PriorityEnum,
    TaskStatusEnum,
    TaskTypeEnum,
    UserRoleEnum,
)
from app.models.supervisor_task_request import SupervisorTaskRequest
from app.models.task_master import TaskMaster
from app.models.user import User


@pytest.fixture
def supervisor_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine)
    current_user = {"value": None}

    def override_get_db():
        db = session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: current_user["value"]
    with session_local() as db:
        department = Department(department_name="Console Test Department")
        other_department = Department(department_name="Other Test Department")
        db.add_all([department, other_department])
        db.flush()
        supervisor_employee = Employee(
            department_id=department.department_id,
            name="Test Supervisor",
            role="Supervisor",
            availability=EmploymentStatusEnum.ACTIVE,
            gender=GenderEnum.FEMALE,
        )
        db.add(supervisor_employee)
        db.flush()
        current_user["value"] = User(
            user_id=1,
            employee_id=supervisor_employee.employee_id,
            department_id=department.department_id,
            email="supervisor@test.local",
            hashed_password="unused",
            role=UserRoleEnum.SUPERVISOR,
            is_active=True,
        )
        db.add_all([
            TaskMaster(
                task_id=1,
                department_id=department.department_id,
                task_name="Department task",
                task_state=TaskStatusEnum.ACTIVE,
                priority_category=PriorityEnum.MEDIUM,
                task_type=TaskTypeEnum.EVENT_TEMPLATE,
            ),
            TaskMaster(
                task_id=2,
                department_id=other_department.department_id,
                task_name="Other department task",
                task_state=TaskStatusEnum.ACTIVE,
                priority_category=PriorityEnum.MEDIUM,
                task_type=TaskTypeEnum.EVENT_TEMPLATE,
            ),
        ])
        db.commit()

    try:
        yield TestClient(app), session_local, current_user
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_supervisor_request_uses_authenticated_employee_and_is_persisted(supervisor_client):
    client, session_local, current_user = supervisor_client
    response = client.post(
        "/supervisor-task-requests/bulk",
        json=[{
            "task_id": 1,
            "supervisor_id": 999,
            "priority": "HIGH",
            "due_offset": "ONE_HOUR",
        }],
    )

    assert response.status_code == 202
    assert response.json()["created"] == 1
    with session_local() as db:
        request = db.query(SupervisorTaskRequest).one()
        assert request.supervisor_id == current_user["value"].employee_id
        assert request.priority == PriorityEnum.HIGH


def test_supervisor_cannot_publish_task_for_another_department(supervisor_client):
    client, session_local, _ = supervisor_client
    response = client.post(
        "/supervisor-task-requests/bulk",
        json=[{
            "task_id": 2,
            "supervisor_id": 1,
            "priority": "HIGH",
        }],
    )

    assert response.status_code == 403
    with session_local() as db:
        assert db.query(SupervisorTaskRequest).count() == 0


def test_supervisor_request_history_is_department_scoped(supervisor_client):
    client, session_local, current_user = supervisor_client
    with session_local() as db:
        db.add_all([
            SupervisorTaskRequest(
                task_id=1,
                supervisor_id=current_user["value"].employee_id,
                priority=PriorityEnum.MEDIUM,
                due_time=datetime.now() + timedelta(hours=1),
            ),
            SupervisorTaskRequest(
                task_id=2,
                supervisor_id=current_user["value"].employee_id,
                priority=PriorityEnum.MEDIUM,
                due_time=datetime.now() + timedelta(hours=1),
            ),
        ])
        db.commit()

    response = client.get("/supervisor-task-requests/")

    assert response.status_code == 200
    assert [item["task_id"] for item in response.json()] == [1]
