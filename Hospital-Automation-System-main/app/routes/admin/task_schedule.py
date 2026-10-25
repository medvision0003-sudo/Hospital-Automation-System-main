from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.database.connection import get_db
from app.models.task_master import TaskMaster
from app.models.task_schedule import TaskSchedule
from app.models.shift import Shift
from app.schemas.task_schedule import TaskScheduleCreate, TaskScheduleUpdate, TaskScheduleResponse
from app.services.recurring_task_scheduler import (
    compute_next_run,
    is_shift_active_now,
    next_shift_start_after,
    signal_scheduler_wake,
)

router = APIRouter(prefix="/schedules", tags=["Admin - Schedules"])


def _validate_shift_for_task(db: Session, shift_id: int, task: TaskMaster):
    """Validate that a shift exists and belongs to the task's department (or is global)."""
    shift = db.query(Shift).filter(Shift.shift_id == shift_id).first()
    if not shift:
        raise HTTPException(status_code=404, detail=f"Shift {shift_id} not found")

    if shift.department_id is not None and shift.department_id != task.department_id:
        raise HTTPException(
            status_code=400,
            detail=f"Shift {shift_id} belongs to department {shift.department_id}, "
                   f"but task belongs to department {task.department_id}",
        )
    return shift


@router.post("/", response_model=TaskScheduleResponse, status_code=201)
def create_schedule(data: TaskScheduleCreate, db: Session = Depends(get_db)):
    task = db.query(TaskMaster).filter(TaskMaster.task_id == data.task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    duplicate = (
        db.query(TaskSchedule)
        .filter(
            TaskSchedule.task_id == data.task_id,
            TaskSchedule.schedule_name == data.schedule_name,
        )
        .first()
    )
    if duplicate:
        raise HTTPException(
            status_code=400,
            detail=f"Schedule '{data.schedule_name}' already exists for task {data.task_id}",
        )

    # Validate shift if provided
    shift = None
    if data.shift_id:
        shift = _validate_shift_for_task(db, data.shift_id, task)

    schedule_dict = data.model_dump()

    # Align next_run: if shift_id supplied and next_run omitted, start at next shift start
    if not schedule_dict.get("next_run"):
        if shift:
            now = datetime.now()
            schedule_dict["next_run"] = (
                now if is_shift_active_now(shift, now)
                else next_shift_start_after(shift, now)
            )
        else:
            schedule_dict["next_run"] = compute_next_run(
                data.frequency_type,
                data.frequency_value,
            )

    schedule = TaskSchedule(**schedule_dict)
    db.add(schedule)
    db.commit()
    db.refresh(schedule)

    signal_scheduler_wake()

    # Eager load shift for the response
    schedule = (
        db.query(TaskSchedule)
        .options(joinedload(TaskSchedule.shift))
        .filter(TaskSchedule.schedule_id == schedule.schedule_id)
        .first()
    )

    return schedule


@router.put("/{schedule_id}", response_model=TaskScheduleResponse)
def update_schedule(schedule_id: int, data: TaskScheduleUpdate, db: Session = Depends(get_db)):
    schedule = (
        db.query(TaskSchedule)
        .filter(TaskSchedule.schedule_id == schedule_id)
        .first()
    )
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    update_fields = data.model_dump(exclude_unset=True)

    # Validate shift if being updated
    if "shift_id" in update_fields and update_fields["shift_id"] is not None:
        task = db.query(TaskMaster).filter(TaskMaster.task_id == schedule.task_id).first()
        _validate_shift_for_task(db, update_fields["shift_id"], task)

    for key, value in update_fields.items():
        setattr(schedule, key, value)

    db.commit()
    db.refresh(schedule)

    signal_scheduler_wake()

    # Eager load shift for the response
    schedule = (
        db.query(TaskSchedule)
        .options(joinedload(TaskSchedule.shift))
        .filter(TaskSchedule.schedule_id == schedule.schedule_id)
        .first()
    )

    return schedule


@router.delete("/{schedule_id}", status_code=200)
def delete_schedule(schedule_id: int, db: Session = Depends(get_db)):
    schedule = (
        db.query(TaskSchedule)
        .filter(TaskSchedule.schedule_id == schedule_id)
        .first()
    )
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    db.delete(schedule)
    db.commit()
    return {"message": f"Schedule {schedule_id} deleted successfully"}
