from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.core.dependencies import get_current_user
from app.database.connection import get_db
from app.models.department import Department
from app.models.department_work_queue import DepartmentWorkQueue
from app.models.enums import UserRoleEnum
from app.models.user import User
from app.schemas.department import DepartmentResponse
from app.schemas.work_queue import WorkQueueResponse

router = APIRouter(prefix="/departments", tags=["Query - Departments"])


@router.get("/", response_model=List[DepartmentResponse])
def get_all_departments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Fetch all active and registered departments
    if current_user.role == UserRoleEnum.SUPERVISOR:
        if current_user.department_id is None:
            raise HTTPException(status_code=403, detail="Supervisor is not linked to a department.")
        return db.query(Department).filter(
            Department.department_id == current_user.department_id
        ).all()
    departments = db.query(Department).all()
    return departments


@router.get("/{department_id}", response_model=DepartmentResponse)
def get_department(
    department_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Department).filter(Department.department_id == department_id)
    if current_user.role == UserRoleEnum.SUPERVISOR:
        if current_user.department_id != department_id:
            raise HTTPException(status_code=404, detail="Department not found")
    department = query.first()

    if not department:
        raise HTTPException(status_code=404, detail="Department not found")

    return department


@router.get("/{department_id}/work-queue", response_model=List[WorkQueueResponse])
def get_department_work_queue(
    department_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    department = get_department(department_id, db, current_user)

    if not department:
        raise HTTPException(status_code=404, detail="Department not found")

    work_items = db.query(DepartmentWorkQueue).filter(
        DepartmentWorkQueue.department_id == department_id
    ).all()

    return work_items
