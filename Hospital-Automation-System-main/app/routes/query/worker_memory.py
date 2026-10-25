from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.database.connection import get_db
from app.models.worker_memory import WorkerMemory
from app.schemas.worker_memory import WorkerMemoryResponse

router = APIRouter(prefix="/worker-memory", tags=["Query - Worker Memory"])


@router.get("/", response_model=List[WorkerMemoryResponse])
def get_all_worker_memories(db: Session = Depends(get_db)):
    """Fetch performance stats for all workers."""
    return db.query(WorkerMemory).all()


@router.get("/{employee_id}", response_model=WorkerMemoryResponse)
def get_worker_memory(employee_id: int, db: Session = Depends(get_db)):
    """Fetch performance stats for a specific worker."""
    memory = db.query(WorkerMemory).filter(
        WorkerMemory.employee_id == employee_id
    ).first()

    if not memory:
        raise HTTPException(status_code=404, detail="Worker memory not found")

    return memory
