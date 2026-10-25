import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.core.dependencies import get_current_user
from app.database.connection import get_db
from app.models.task_assignment import TaskAssignment
from app.models.department_work_queue import DepartmentWorkQueue
from app.models.enums import AssignmentStatusEnum, UserRoleEnum
from app.models.user import User
from app.schemas.task_assignment import TaskAssignmentResponse

router = APIRouter(prefix="/assignments", tags=["Query - Assignments"])
logger = logging.getLogger(__name__)


@router.get("", response_model=List[TaskAssignmentResponse])
@router.get("/", response_model=List[TaskAssignmentResponse])
def get_all_assignments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch every task assignment."""
    query = db.query(TaskAssignment)
    if current_user.role == UserRoleEnum.SUPERVISOR:
        if current_user.department_id is None:
            raise HTTPException(status_code=403, detail="Supervisor is not linked to a department.")
        query = query.join(
            DepartmentWorkQueue,
            TaskAssignment.work_id == DepartmentWorkQueue.work_id,
        ).filter(DepartmentWorkQueue.department_id == current_user.department_id)
    return query.all()


@router.get("/{assignment_id}", response_model=TaskAssignmentResponse)
def get_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch one assignment by ID."""
    query = db.query(TaskAssignment).filter(TaskAssignment.assignment_id == assignment_id)
    if current_user.role == UserRoleEnum.SUPERVISOR:
        if current_user.department_id is None:
            raise HTTPException(status_code=403, detail="Supervisor is not linked to a department.")
        query = query.join(
            DepartmentWorkQueue,
            TaskAssignment.work_id == DepartmentWorkQueue.work_id,
        ).filter(DepartmentWorkQueue.department_id == current_user.department_id)
    assignment = query.first()

    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    return assignment




@router.post("/{assignment_id}/preempt")
def preempt_assignment_endpoint(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Preempt (remove) a task assignment from an employee.

    Only ASSIGNED tasks can be preempted. Tasks that are IN_PROGRESS,
    COMPLETED, CANCELLED, or already PREEMPTED will be rejected.
    After preemption, a follow-up assignment cycle runs to auto-assign
    the freed task to another eligible worker in the same department.
    """
    from app.agents.assignment_agent import preempt_assignment, run_assignment_cycle

    assignment = db.query(TaskAssignment).filter(
        TaskAssignment.assignment_id == assignment_id
    ).first()

    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    # Guard: only ASSIGNED status can be preempted by supervisor
    status = assignment.assignment_status
    if status != AssignmentStatusEnum.ASSIGNED:
        status_label = status.value if status else "UNKNOWN"
        if status == AssignmentStatusEnum.IN_PROGRESS:
            raise HTTPException(
                status_code=400,
                detail="Cannot remove a task that is currently IN_PROGRESS. "
                       "The employee must complete or cancel it first.",
            )
        raise HTTPException(
            status_code=400,
            detail=f"Assignment cannot be preempted (current status: {status_label}).",
        )

    # Resolve department_id from work queue for the follow-up cycle
    work_item = db.query(DepartmentWorkQueue).filter(
        DepartmentWorkQueue.work_id == assignment.work_id
    ).first()
    department_id = work_item.department_id if work_item else None
    if current_user.role == UserRoleEnum.SUPERVISOR and (
        current_user.department_id is None
        or department_id != current_user.department_id
    ):
        raise HTTPException(status_code=404, detail="Assignment not found")
    if current_user.role not in (UserRoleEnum.SUPERVISOR, UserRoleEnum.ADMIN):
        raise HTTPException(status_code=403, detail="Only supervisors and administrators can preempt assignments.")

    # Execute preemption using the existing Assignment Agent logic
    freed_work_id = preempt_assignment(
        assignment_id=assignment_id,
        db=db,
        reason="Supervisor manually removed assignment via Employee Work Status",
        source_module="SUPERVISOR_CONSOLE",
    )
    db.commit()
    from app.services.outbox_dispatcher import signal_outbox_wake
    signal_outbox_wake()

    # Trigger follow-up assignment cycle to reassign the freed task
    cycle_result = None
    cycle_error = None
    if department_id:
        try:
            cycle_result = run_assignment_cycle(
                department_id=department_id,
                db=db,
                trigger="SUPERVISOR_PREEMPTION",
            )
        except Exception as exc:
            logger.exception("Follow-up assignment cycle failed for freed work %s", freed_work_id)
            cycle_error = str(exc)

    raw_cycle_status = cycle_result.get("status") if cycle_result else None
    cycle_status = getattr(raw_cycle_status, "value", raw_cycle_status)
    return {
        "status": "preempted",
        "assignment_id": assignment_id,
        "freed_work_id": freed_work_id,
        "employee_id": assignment.employee_id,
        "reassignment_result": {
            "total_assigned": cycle_result.get("total_assigned", 0) if cycle_result else 0,
            "status": str(cycle_status or ("FAILED" if cycle_error else "SKIPPED")),
            "error": cycle_error,
        },
    }
