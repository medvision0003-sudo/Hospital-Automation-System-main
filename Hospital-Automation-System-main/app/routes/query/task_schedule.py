from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import List

from app.database.connection import get_db
from app.models.task_schedule import TaskSchedule
from app.schemas.task_schedule import TaskScheduleResponse

router = APIRouter(prefix="/schedules", tags=["Query - Schedules"])


@router.get("/", response_model=List[TaskScheduleResponse])
def get_all_schedules(db: Session = Depends(get_db)):
    schedules = (
        db.query(TaskSchedule)
        .options(joinedload(TaskSchedule.shift))
        .all()
    )
    return schedules


@router.get("/{schedule_id}", response_model=TaskScheduleResponse)
def get_schedule(schedule_id: int, db: Session = Depends(get_db)):
    schedule = (
        db.query(TaskSchedule)
        .options(joinedload(TaskSchedule.shift))
        .filter(TaskSchedule.schedule_id == schedule_id)
        .first()
    )
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return schedule


@router.get("/by-task/{task_id}", response_model=List[TaskScheduleResponse])
def get_schedules_for_task(task_id: int, db: Session = Depends(get_db)):
    schedules = (
        db.query(TaskSchedule)
        .options(joinedload(TaskSchedule.shift))
        .filter(TaskSchedule.task_id == task_id)
        .all()
    )
    return schedules
