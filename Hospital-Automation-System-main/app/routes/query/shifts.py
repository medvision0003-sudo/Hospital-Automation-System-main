from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List, Optional

from app.database.connection import get_db
from app.models.shift import Shift
from app.schemas.shift import ShiftResponse

router = APIRouter(prefix="/shifts", tags=["Query - Shifts"])


@router.get("/", response_model=List[ShiftResponse])
def get_all_shifts(
    department_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """Fetch shift definitions, optionally filtered by department.

    When department_id is provided, returns shifts belonging to that
    department plus global templates (department_id IS NULL).
    When omitted, returns every shift definition.
    """
    query = db.query(Shift)
    if department_id is not None:
        query = query.filter(
            or_(
                Shift.department_id == department_id,
                Shift.department_id.is_(None),
            )
        )
    return query.all()


@router.get("/{shift_id}", response_model=ShiftResponse)
def get_shift(shift_id: int, db: Session = Depends(get_db)):
    """Fetch one shift by ID."""
    shift = db.query(Shift).filter(Shift.shift_id == shift_id).first()

    if not shift:
        raise HTTPException(status_code=404, detail="Shift not found")

    return shift
