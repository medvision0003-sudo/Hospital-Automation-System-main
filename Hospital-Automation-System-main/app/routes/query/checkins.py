from datetime import date, datetime, time, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.database.connection import get_db
from app.models.employee import Employee
from app.models.enums import UserRoleEnum
from app.models.user import User
from app.models.worker_checkin import WorkerCheckin
from app.schemas.worker_checkin import WorkerCheckinResponse

router = APIRouter(prefix="/checkins", tags=["Query - Check-ins"])


@router.get("", response_model=List[WorkerCheckinResponse])
@router.get("/", response_model=List[WorkerCheckinResponse])
def get_all_checkins(db: Session = Depends(get_db)):
    """Fetch every check-in record."""
    return db.query(WorkerCheckin).all()


@router.get("/range", response_model=List[WorkerCheckinResponse])
def get_checkins_range(
    start_date: date = Query(...),
    end_date: date = Query(...),
    department_id: Optional[int] = Query(None, gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch check-ins for a bounded date range, optionally filtered by department."""
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="end_date must be on or after start_date.")
    if (end_date - start_date).days > 31:
        raise HTTPException(status_code=400, detail="Check-in ranges cannot exceed 32 days.")

    query = (
        db.query(WorkerCheckin)
        .join(Employee, WorkerCheckin.employee_id == Employee.employee_id)
        .filter(
            WorkerCheckin.checkin_time >= datetime.combine(start_date, time.min),
            WorkerCheckin.checkin_time < datetime.combine(end_date + timedelta(days=1), time.min),
        )
    )
    if current_user.role == UserRoleEnum.SUPERVISOR:
        if current_user.department_id is None:
            raise HTTPException(status_code=403, detail="Supervisor is not linked to a department.")
        if department_id is not None and department_id != current_user.department_id:
            raise HTTPException(status_code=404, detail="Check-in records not found.")
        department_id = current_user.department_id
    if department_id is not None:
        query = query.filter(Employee.department_id == department_id)

    return query.order_by(WorkerCheckin.checkin_time, WorkerCheckin.employee_id).all()


@router.get("/year", response_model=List[WorkerCheckinResponse])
def get_checkins_year(
    year: int = Query(..., ge=2000, le=2100),
    department_id: Optional[int] = Query(None, gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch a calendar year's check-ins for annual attendance summaries."""
    query = (
        db.query(WorkerCheckin)
        .join(Employee, WorkerCheckin.employee_id == Employee.employee_id)
        .filter(
            WorkerCheckin.checkin_time >= datetime(year, 1, 1),
            WorkerCheckin.checkin_time < datetime(year + 1, 1, 1),
        )
    )
    if current_user.role == UserRoleEnum.SUPERVISOR:
        if current_user.department_id is None:
            raise HTTPException(status_code=403, detail="Supervisor is not linked to a department.")
        if department_id is not None and department_id != current_user.department_id:
            raise HTTPException(status_code=404, detail="Check-in records not found.")
        department_id = current_user.department_id
    if department_id is not None:
        query = query.filter(Employee.department_id == department_id)

    return query.order_by(WorkerCheckin.checkin_time, WorkerCheckin.employee_id).all()
