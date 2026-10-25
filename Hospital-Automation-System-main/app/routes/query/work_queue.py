from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.core.dependencies import get_current_user
from app.database.connection import get_db
from app.models.department_work_queue import DepartmentWorkQueue
from app.models.enums import UserRoleEnum
from app.models.task_proof import TaskProof
from app.models.user import User
from app.schemas.work_queue import WorkQueueResponse

router = APIRouter(prefix="/work-queue", tags=["Query - Work Queue"])


def _enrich_with_proof(work_item: DepartmentWorkQueue) -> dict:
    """Build a response dict that includes the latest proof details."""
    data = {
        "work_id": work_item.work_id,
        "task_id": work_item.task_id,
        "department_id": work_item.department_id,
        "shift_id": work_item.shift_id,
        "priority": work_item.priority.value if work_item.priority else None,
        "queue_status": work_item.queue_status.value if work_item.queue_status else None,
        "created_at": work_item.created_at,
        "due_date": work_item.due_date,
        "proof_image_path": None,
        "verification_status": None,
        "verification_confidence": None,
        "verification_rationale": None,
        "ai_decision": None,
        "proof_employee_id": None,
        "verification_attempts": None,
    }

    # Map latest proof details if any exist
    if work_item.proofs:
        latest = work_item.proofs[0]
        data["proof_image_path"] = latest.proof_image_path
        data["verification_status"] = latest.verification_status.value if latest.verification_status else None
        data["verification_confidence"] = latest.verification_confidence
        data["verification_rationale"] = latest.verification_rationale
        data["ai_decision"] = latest.ai_decision
        data["proof_employee_id"] = latest.employee_id
        data["verification_attempts"] = latest.verification_attempts

    return data


@router.get("/", response_model=List[WorkQueueResponse])
def get_all_work_queue(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(DepartmentWorkQueue)
    if current_user.role == UserRoleEnum.SUPERVISOR:
        if current_user.department_id is None:
            raise HTTPException(status_code=403, detail="Supervisor is not linked to a department.")
        query = query.filter(DepartmentWorkQueue.department_id == current_user.department_id)
    work_items = query.all()
    return [_enrich_with_proof(item) for item in work_items]


@router.get("/{work_id}", response_model=WorkQueueResponse)
def get_work_queue_item(
    work_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(DepartmentWorkQueue).filter(DepartmentWorkQueue.work_id == work_id)
    if current_user.role == UserRoleEnum.SUPERVISOR:
        if current_user.department_id is None:
            raise HTTPException(status_code=403, detail="Supervisor is not linked to a department.")
        query = query.filter(DepartmentWorkQueue.department_id == current_user.department_id)
    work_item = query.first()

    if not work_item:
        raise HTTPException(status_code=404, detail="Work queue item not found")

    return _enrich_with_proof(work_item)
