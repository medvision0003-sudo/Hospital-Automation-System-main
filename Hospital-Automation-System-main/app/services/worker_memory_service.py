from sqlalchemy.orm import Session

from app.models.enums import AssignmentStatusEnum
from app.models.task_assignment import TaskAssignment
from app.models.worker_memory import WorkerMemory


def get_or_create_worker_memory(db: Session, employee_id: int) -> WorkerMemory:
    memory = db.query(WorkerMemory).filter(
        WorkerMemory.employee_id == employee_id,
    ).first()
    if memory:
        return memory

    active_assignments = db.query(TaskAssignment).filter(
        TaskAssignment.employee_id == employee_id,
        TaskAssignment.assignment_status.in_([
            AssignmentStatusEnum.ASSIGNED,
            AssignmentStatusEnum.IN_PROGRESS,
        ]),
    ).count()
    completed_assignments = db.query(TaskAssignment).filter(
        TaskAssignment.employee_id == employee_id,
        TaskAssignment.assignment_status == AssignmentStatusEnum.COMPLETED,
    ).count()
    memory = WorkerMemory(
        employee_id=employee_id,
        pending_task=active_assignments,
        total_task_completed=completed_assignments,
    )
    db.add(memory)
    db.flush()
    return memory
