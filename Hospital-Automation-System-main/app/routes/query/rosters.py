from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date

from app.core.dependencies import get_current_user
from app.database.connection import get_db
from app.models.enums import RosterStatusEnum, UserRoleEnum
from app.models.shift_roster import ShiftRoster
from app.models.employee import Employee
from app.models.shift import Shift
from app.models.user import User
from app.schemas.shift_roster import ShiftRosterResponse, ShiftRosterCreate
from app.services.recurring_task_scheduler import signal_scheduler_wake
from pydantic import BaseModel

# The /rosters routes interact with the ShiftRoster model, which maps to the "shift_scheduler" database table.
# This aligns with the frontend's shift scheduler interface.
router = APIRouter(prefix="/rosters", tags=["Query - Rosters"])


@router.get("/", response_model=List[ShiftRosterResponse])
def get_all_rosters(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch every roster entry."""
    query = db.query(ShiftRoster)
    if current_user.role == UserRoleEnum.SUPERVISOR:
        if current_user.department_id is None:
            raise HTTPException(status_code=403, detail="Supervisor is not linked to a department.")
        query = query.join(Employee, ShiftRoster.employee_id == Employee.employee_id).filter(
            Employee.department_id == current_user.department_id
        )
    return query.all()


@router.get("/range", response_model=List[ShiftRosterResponse])
def get_rosters_range(
    start_date: date = Query(...),
    end_date: date = Query(...),
    department_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch roster entries within a date range, optionally filtered by department."""
    query = (
        db.query(ShiftRoster)
        .join(Employee, ShiftRoster.employee_id == Employee.employee_id)
        .filter(
            ShiftRoster.work_date >= start_date,
            ShiftRoster.work_date <= end_date,
        )
    )
    if current_user.role == UserRoleEnum.SUPERVISOR:
        if current_user.department_id is None:
            raise HTTPException(status_code=403, detail="Supervisor is not linked to a department.")
        if department_id is not None and department_id != current_user.department_id:
            raise HTTPException(status_code=404, detail="Roster entries not found.")
        department_id = current_user.department_id
    if department_id:
        query = query.filter(Employee.department_id == department_id)
    return query.all()


class BulkRosterItem(BaseModel):
    employee_id: int
    shift_id: Optional[int] = None
    work_date: date
    roster_status: Optional[RosterStatusEnum] = RosterStatusEnum.SCHEDULED


class BulkRosterRequest(BaseModel):
    items: List[BulkRosterItem]


@router.post("/bulk")
def bulk_save_rosters(
    payload: BulkRosterRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Bulk create or update per-shift roster entries.

    A null shift_id clears every shift for that employee and date.
    """
    employee_ids = {item.employee_id for item in payload.items}
    employees = {
        employee.employee_id: employee
        for employee in db.query(Employee).filter(Employee.employee_id.in_(employee_ids)).all()
    }
    missing_employees = employee_ids - employees.keys()
    if missing_employees:
        raise HTTPException(
            status_code=404,
            detail=f"Employee not found: {', '.join(map(str, sorted(missing_employees)))}",
        )
    if current_user.role == UserRoleEnum.SUPERVISOR:
        if current_user.department_id is None:
            raise HTTPException(status_code=403, detail="Supervisor is not linked to a department.")
        if any(employee.department_id != current_user.department_id for employee in employees.values()):
            raise HTTPException(status_code=403, detail="Supervisors can only manage rosters in their department.")
    for item in payload.items:
        if item.shift_id is not None:
            shift = db.query(Shift).filter(Shift.shift_id == item.shift_id).first()
            if shift is None:
                raise HTTPException(status_code=404, detail=f"Shift {item.shift_id} not found.")
            if (
                current_user.role == UserRoleEnum.SUPERVISOR
                and shift.department_id not in (None, current_user.department_id)
            ):
                raise HTTPException(status_code=403, detail="Shift does not belong to the supervisor's department.")

    created = 0
    updated = 0
    deleted = 0

    for item in payload.items:
        matching_entries = db.query(ShiftRoster).filter(
            ShiftRoster.employee_id == item.employee_id,
            ShiftRoster.work_date == item.work_date,
        )

        if item.shift_id is None:
            entries = matching_entries.all()
            for entry in entries:
                db.delete(entry)
            deleted += len(entries)
            continue

        entries = matching_entries.filter(
            ShiftRoster.shift_id == item.shift_id,
        ).order_by(ShiftRoster.roster_id).all()
        if entries:
            existing = entries[0]
            existing.shift_id = item.shift_id
            existing.roster_status = item.roster_status or RosterStatusEnum.SCHEDULED
            updated += 1
            for duplicate in entries[1:]:
                db.delete(duplicate)
                deleted += 1
        else:
            new_roster = ShiftRoster(
                employee_id=item.employee_id,
                shift_id=item.shift_id,
                work_date=item.work_date,
                roster_status=item.roster_status or RosterStatusEnum.SCHEDULED,
            )
            db.add(new_roster)
            created += 1

    db.commit()
    signal_scheduler_wake()
    return {"created": created, "updated": updated, "deleted": deleted}


@router.get("/{roster_id}", response_model=ShiftRosterResponse)
def get_roster(
    roster_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch one roster entry by ID."""
    query = db.query(ShiftRoster).filter(ShiftRoster.roster_id == roster_id)
    if current_user.role == UserRoleEnum.SUPERVISOR:
        if current_user.department_id is None:
            raise HTTPException(status_code=403, detail="Supervisor is not linked to a department.")
        query = query.join(Employee, ShiftRoster.employee_id == Employee.employee_id).filter(
            Employee.department_id == current_user.department_id
        )
    roster = query.first()

    if not roster:
        raise HTTPException(status_code=404, detail="Roster entry not found")

    return roster


@router.get(
    "/employee/{employee_id}",
    response_model=List[ShiftRosterResponse],
)
def get_rosters_by_employee(
    employee_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch all roster entries for a specific employee."""
    employee = db.query(Employee).filter(Employee.employee_id == employee_id).first()
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    if current_user.role == UserRoleEnum.SUPERVISOR and (
        current_user.department_id is None
        or employee.department_id != current_user.department_id
    ):
        raise HTTPException(status_code=404, detail="Employee not found")
    return db.query(ShiftRoster).filter(
        ShiftRoster.employee_id == employee_id
    ).all()
