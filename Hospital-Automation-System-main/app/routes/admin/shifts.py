from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.models.shift import Shift
from app.schemas.shift import ShiftCreate, ShiftUpdate, ShiftResponse

router = APIRouter(prefix="/shifts", tags=["Admin - Shifts"])


@router.post("/", response_model=ShiftResponse, status_code=201)
def create_shift(data: ShiftCreate, db: Session = Depends(get_db)):
    """Create a new shift definition for a department."""
    new_shift = Shift(**data.model_dump())
    db.add(new_shift)
    db.commit()
    db.refresh(new_shift)
    return new_shift


@router.put("/{shift_id}", response_model=ShiftResponse)
def update_shift(
    shift_id: int,
    data: ShiftUpdate,
    db: Session = Depends(get_db),
):
    """Update an existing shift definition (partial update)."""
    shift = db.query(Shift).filter(Shift.shift_id == shift_id).first()

    if not shift:
        raise HTTPException(status_code=404, detail="Shift not found")

    # Route-level check for partial updates where only one time field is sent
    update_fields = data.model_dump(exclude_unset=True)
    eff_start = update_fields.get("start_time", shift.start_time)
    eff_end = update_fields.get("end_time", shift.end_time)
    if eff_start == eff_end:
        raise HTTPException(
            status_code=400,
            detail="start_time and end_time cannot be equal; "
                   "24-hour recurring shift windows are not supported",
        )

    for field, value in update_fields.items():
        setattr(shift, field, value)

    db.commit()
    db.refresh(shift)
    return shift


@router.delete("/{shift_id}", status_code=200)
def delete_shift(shift_id: int, db: Session = Depends(get_db)):
    """Delete a shift by ID."""
    shift = db.query(Shift).filter(Shift.shift_id == shift_id).first()

    if not shift:
        raise HTTPException(status_code=404, detail="Shift not found")

    db.delete(shift)
    db.commit()
    return {"message": f"Shift {shift_id} deleted successfully"}
