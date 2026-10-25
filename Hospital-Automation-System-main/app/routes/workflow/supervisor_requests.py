"""
Supervisor Task Requests -- DB insertion + outbox event routes.

POST /supervisor-task-requests/       creates a single request record.
POST /supervisor-task-requests/bulk   creates multiple request records atomically.

Each record is committed atomically with a SUPERVISOR_REQUEST_CREATED
outbox event in the service layer, so the outbox dispatcher daemon
picks it up for orchestrator processing.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.dependencies import require_roles
from app.database.connection import get_db
from app.models.enums import TaskStatusEnum, UserRoleEnum
from app.models.task_master import TaskMaster
from app.models.user import User
from app.schemas.supervisor_task_request import (
    SupervisorTaskRequestCreate,
    SupervisorTaskRequestResponse,
    SupervisorTaskRequestsBulkResponse,
)
from app.services.supervisor import (
    create_supervisor_request,
    create_supervisor_requests_bulk,
)

router = APIRouter(prefix="/supervisor-task-requests", tags=["Workflow - Supervisor Requests"])


def _validate_supervisor_scope(
    db: Session,
    body: SupervisorTaskRequestCreate,
    user: User,
) -> SupervisorTaskRequestCreate:
    if user.employee_id is None or user.department_id is None:
        raise HTTPException(
            status_code=403,
            detail="A supervisor account must be linked to an employee and department to publish tasks.",
        )

    task = db.query(TaskMaster).filter(TaskMaster.task_id == body.task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {body.task_id} not found.")
    if task.task_state != TaskStatusEnum.ACTIVE:
        raise HTTPException(status_code=409, detail=f"Task {body.task_id} is not active.")
    if task.department_id not in (None, user.department_id):
        raise HTTPException(status_code=403, detail="Supervisors can only publish tasks for their department.")

    return body.model_copy(update={"supervisor_id": user.employee_id})


@router.post("/", response_model=SupervisorTaskRequestResponse, status_code=202)
def create_single_supervisor_task_request(
    body: SupervisorTaskRequestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRoleEnum.SUPERVISOR])),
):
    return create_supervisor_request(db, _validate_supervisor_scope(db, body, current_user))


@router.post("/bulk", response_model=SupervisorTaskRequestsBulkResponse, status_code=202)
def create_bulk_supervisor_task_requests(
    body: list[SupervisorTaskRequestCreate],
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles([UserRoleEnum.SUPERVISOR])),
):
    if not body:
        raise HTTPException(status_code=422, detail="At least one task request is required.")
    scoped_requests = [_validate_supervisor_scope(db, item, current_user) for item in body]
    return create_supervisor_requests_bulk(db, scoped_requests)
