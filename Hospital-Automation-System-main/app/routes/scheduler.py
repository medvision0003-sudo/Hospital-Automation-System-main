from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload
from typing import List

from app.database.connection import get_db
from app.models.task_master import TaskMaster
from app.models.task_schedule import TaskSchedule
from app.models.enums import TaskStatusEnum, UserRoleEnum
from app.schemas.task_schedule import TaskScheduleResponse
from app.services.recurring_task_scheduler import generate_scheduled_tasks
from app.core.dependencies import require_roles

router = APIRouter(prefix="/scheduler", tags=["Scheduler"])


@router.post("/run", dependencies=[Depends(require_roles([UserRoleEnum.ADMIN]))])
def run_scheduler(db: Session = Depends(get_db)):
    """Manually trigger one scheduler cycle to generate due recurring tasks.
    Restricted to ADMIN users only.
    """
    result = generate_scheduled_tasks(db)
    return result


@router.get("/upcoming", response_model=List[TaskScheduleResponse])
def get_upcoming_schedules(db: Session = Depends(get_db)):
    """List all active schedules sorted by next_run."""
    schedules = (
        db.query(TaskSchedule)
        .join(TaskMaster, TaskSchedule.task_id == TaskMaster.task_id)
        .options(joinedload(TaskSchedule.shift))
        .filter(
            TaskSchedule.is_active == True,
            TaskMaster.task_state == TaskStatusEnum.ACTIVE,
            TaskSchedule.next_run.isnot(None),
        )
        .order_by(TaskSchedule.next_run.asc())
        .all()
    )
    return schedules

