"""
Admin endpoint for updating worker memory / profile fields.

Conceptual Split Rule:
    - Profile fields (skills, certifications, etc.) -> editable by admins via this API.
    - Operational fields (pending_task, total_task_completed, last_updated)
      -> updated ONLY by agents. This endpoint should NOT be used to modify them.

    Today the WorkerMemory model only has operational fields, so the current
    WorkerMemoryUpdate schema still exposes them. As profile columns are added
    to the model, create a WorkerMemoryProfileUpdate schema that excludes
    operational fields and swap it in here.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.models.worker_memory import WorkerMemory
from app.schemas.worker_memory import WorkerMemoryUpdate, WorkerMemoryResponse

router = APIRouter(prefix="/worker-memory", tags=["Admin - Worker Memory"])


@router.put("/{employee_id}", response_model=WorkerMemoryResponse)
def update_worker_memory(
    employee_id: int,
    data: WorkerMemoryUpdate,
    db: Session = Depends(get_db),
):
    """Update profile/configuration fields for a worker.

    NOTE: Operational metrics (pending_task, total_task_completed, etc.)
    should only be modified by agents. Once profile fields are added,
    swap WorkerMemoryUpdate for WorkerMemoryProfileUpdate."""
    memory = db.query(WorkerMemory).filter(
        WorkerMemory.employee_id == employee_id
    ).first()

    if not memory:
        raise HTTPException(status_code=404, detail="Worker memory not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(memory, field, value)

    db.commit()
    db.refresh(memory)
    return memory
