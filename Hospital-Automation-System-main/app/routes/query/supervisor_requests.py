from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.dependencies import get_current_user
from app.database.connection import get_db
from app.models.enums import UserRoleEnum
from app.models.supervisor_task_request import SupervisorTaskRequest
from app.models.task_master import TaskMaster
from app.models.user import User
from app.schemas.supervisor_task_request import SupervisorTaskRequestResponse

router = APIRouter(prefix="/supervisor-task-requests", tags=["Query - Supervisor Requests"])


@router.get("/", response_model=List[SupervisorTaskRequestResponse])
def list_supervisor_task_requests(
    processed: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(SupervisorTaskRequest)
    if current_user.role == UserRoleEnum.SUPERVISOR:
        if current_user.department_id is None:
            raise HTTPException(status_code=403, detail="Supervisor is not linked to a department.")
        query = query.join(TaskMaster, SupervisorTaskRequest.task_id == TaskMaster.task_id).filter(
            (TaskMaster.department_id == current_user.department_id)
            | TaskMaster.department_id.is_(None)
        )

    if processed is True:
        query = query.filter(SupervisorTaskRequest.processed_at.isnot(None))
    elif processed is False:
        query = query.filter(SupervisorTaskRequest.processed_at.is_(None))

    return query.order_by(SupervisorTaskRequest.created_at.desc()).all()


@router.get("/{request_id}", response_model=SupervisorTaskRequestResponse)
def get_supervisor_task_request(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    request = (
        db.query(SupervisorTaskRequest)
        .filter(SupervisorTaskRequest.request_id == request_id)
        .first()
    )
    if not request:
        raise HTTPException(status_code=404, detail="Supervisor task request not found")
    if current_user.role == UserRoleEnum.SUPERVISOR:
        task = db.query(TaskMaster).filter(TaskMaster.task_id == request.task_id).first()
        if current_user.department_id is None or task is None or task.department_id not in (
            None,
            current_user.department_id,
        ):
            raise HTTPException(status_code=404, detail="Supervisor task request not found")
    return request
