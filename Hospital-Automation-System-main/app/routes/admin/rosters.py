from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.models.shift_roster import ShiftRoster
from app.schemas.shift_roster import (
    ShiftRosterCreate,
    ShiftRosterUpdate,
    ShiftRosterResponse,
)
from app.services.recurring_task_scheduler import signal_scheduler_wake

# The /rosters routes interact with the ShiftRoster model, which maps to the "shift_scheduler" database table.
# This aligns with the frontend's shift scheduler interface.
router = APIRouter(prefix="/rosters", tags=["Admin - Rosters"])


@router.post("/", response_model=ShiftRosterResponse, status_code=201)
def create_roster(data: ShiftRosterCreate, db: Session = Depends(get_db)):
    """Create a new shift roster entry for a specific employee and date."""
    existing = db.query(ShiftRoster).filter(
        ShiftRoster.employee_id == data.employee_id,
        ShiftRoster.shift_id == data.shift_id,
        ShiftRoster.work_date == data.work_date,
    ).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail="This employee already has this shift on the selected date.",
        )

    new_roster = ShiftRoster(**data.model_dump())
    db.add(new_roster)
    db.commit()
    db.refresh(new_roster)
    signal_scheduler_wake()
    return new_roster


@router.put("/{roster_id}", response_model=ShiftRosterResponse)
def update_roster(
    roster_id: int,
    data: ShiftRosterUpdate,
    db: Session = Depends(get_db),
):
    """Update an existing roster entry (partial update)."""
    roster = db.query(ShiftRoster).filter(
        ShiftRoster.roster_id == roster_id
    ).first()

    if not roster:
        raise HTTPException(status_code=404, detail="Roster entry not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(roster, field, value)

    db.commit()
    db.refresh(roster)
    signal_scheduler_wake()
    return roster


@router.delete("/{roster_id}", status_code=200)
def delete_roster(roster_id: int, db: Session = Depends(get_db)):
    """Delete a roster entry by ID."""
    roster = db.query(ShiftRoster).filter(
        ShiftRoster.roster_id == roster_id
    ).first()

    if not roster:
        raise HTTPException(status_code=404, detail="Roster entry not found")

    db.delete(roster)
    db.commit()
    signal_scheduler_wake()
    return {"message": f"Roster entry {roster_id} deleted successfully"}
