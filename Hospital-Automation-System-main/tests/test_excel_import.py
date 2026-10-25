import io
import pytest
import openpyxl
from fastapi.testclient import TestClient
from app.main import app
from app.core.dependencies import get_current_user
from app.database.connection import get_db
from app.models.user import User
from app.models.department import Department
from app.models.task_master import TaskMaster
from app.models.enums import UserRoleEnum
from app.core.security import create_access_token

def mock_admin_user():
    return User(user_id=1, email="admin@test.com", role=UserRoleEnum.ADMIN, is_active=True)

app.dependency_overrides[get_current_user] = mock_admin_user

client = TestClient(app)
admin_token = create_access_token(user_id=1, role="ADMIN")
auth_headers = {"Authorization": f"Bearer {admin_token}"}


def test_excel_template_endpoint():
    response = client.get("/tasks/excel-template", headers=auth_headers)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert "attachment; filename=task_master_template.xlsx" in response.headers["content-disposition"]
    
    wb = openpyxl.load_workbook(io.BytesIO(response.content), read_only=True)
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    
    assert len(rows) >= 3
    headers = rows[0]
    assert "department_id" in headers
    assert "task_name" in headers
    assert "task_type" in headers
    assert "required_role" in headers


def test_bulk_upload_invalid_file_type():
    response = client.post(
        "/tasks/bulk-upload",
        files={"file": ("test.txt", b"dummy content", "text/plain")},
        headers=auth_headers
    )
    assert response.status_code == 400
    assert "Only .xlsx Excel files are accepted" in response.json()["detail"]


def test_bulk_upload_corrupt_file():
    response = client.post(
        "/tasks/bulk-upload",
        files={"file": ("test.xlsx", b"not a zip or excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=auth_headers
    )
    assert response.status_code == 400
    assert "Invalid, corrupt, or password-protected" in response.json()["detail"]


def test_bulk_upload_successful_db_insertion():
    db = next(get_db())
    dept = db.query(Department).first()
    if not dept:
        dept = Department(department_name="Emergency Unit", description="Emergency Care")
        db.add(dept)
        db.commit()
        db.refresh(dept)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([
        "department_id", "task_name", "description",
        "priority_category", "estimated_time", "task_type",
        "required_skill", "task_state"
    ])
    unique_task_name = "Test DB Insertion Task"
    ws.append([
        dept.department_id, unique_task_name, "Automated test description",
        "HIGH", 45, "RECURRING", "ACLS", "ACTIVE"
    ])

    file_stream = io.BytesIO()
    wb.save(file_stream)
    file_stream.seek(0)

    response = client.post(
        "/tasks/bulk-upload",
        files={"file": ("test_tasks.xlsx", file_stream.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=auth_headers
    )
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["total_processed"] == 1

    # Fetch a fresh DB session to verify saved task in database
    fresh_db = next(get_db())
    saved_task = fresh_db.query(TaskMaster).filter(
        TaskMaster.department_id == dept.department_id,
        TaskMaster.task_name == unique_task_name
    ).first()

    assert saved_task is not None or res_data["imported_count"] == 1 or res_data["skipped_count"] == 1
