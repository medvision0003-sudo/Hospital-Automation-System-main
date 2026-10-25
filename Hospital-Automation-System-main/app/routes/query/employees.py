from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List

from app.core.dependencies import get_current_user
from app.database.connection import get_db
from app.models.employee import Employee
from app.models.worker_memory import WorkerMemory
from app.models.department import Department
from app.models.task_assignment import TaskAssignment
from app.models.department_work_queue import DepartmentWorkQueue
from app.models.enums import AssignmentStatusEnum, PriorityEnum, UserRoleEnum
from app.models.user import User
from app.models.worker_checkin import WorkerCheckin
from app.schemas.employee import EmployeeResponse
from app.schemas.task_assignment import TaskAssignmentResponse
from app.schemas.worker_checkin import WorkerCheckinResponse

router = APIRouter(prefix="/employees", tags=["Query - Employees"])


def _get_scoped_employee(db: Session, employee_id: int, current_user: User) -> Employee:
    employee = db.query(Employee).filter(Employee.employee_id == employee_id).first()
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    if current_user.role == UserRoleEnum.SUPERVISOR and (
        current_user.department_id is None
        or employee.department_id != current_user.department_id
    ):
        raise HTTPException(status_code=404, detail="Employee not found")
    return employee


@router.get("/", response_model=List[EmployeeResponse])
def get_all_employees(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch every employee with workload metrics for player card display."""
    query = db.query(Employee)
    if current_user.role == UserRoleEnum.SUPERVISOR:
        if current_user.department_id is None:
            raise HTTPException(status_code=403, detail="Supervisor is not linked to a department.")
        query = query.filter(Employee.department_id == current_user.department_id)
    employees = query.all()
    results = []
    for emp in employees:
        # Count active assignments (ASSIGNED or IN_PROGRESS) dynamically to stay in sync with work status
        pending = (
            db.query(func.count(TaskAssignment.assignment_id))
            .filter(
                TaskAssignment.employee_id == emp.employee_id,
                TaskAssignment.assignment_status.in_([
                    AssignmentStatusEnum.ASSIGNED,
                    AssignmentStatusEnum.IN_PROGRESS,
                ]),
            )
            .scalar()
        ) or 0

        # Worker memory metrics
        memory = emp.worker_memory
        completed = memory.total_task_completed if memory else 0

        # Count active HIGH/CRITICAL assignments (ASSIGNED or IN_PROGRESS)
        high_crit_count = (
            db.query(func.count(TaskAssignment.assignment_id))
            .join(DepartmentWorkQueue, TaskAssignment.work_id == DepartmentWorkQueue.work_id)
            .filter(
                TaskAssignment.employee_id == emp.employee_id,
                TaskAssignment.assignment_status.in_([
                    AssignmentStatusEnum.ASSIGNED,
                    AssignmentStatusEnum.IN_PROGRESS,
                ]),
                DepartmentWorkQueue.priority.in_([
                    PriorityEnum.HIGH,
                    PriorityEnum.CRITICAL,
                ]),
            )
            .scalar()
        )

        # Department name
        dept_name = emp.department.department_name if emp.department else None

        results.append(EmployeeResponse(
            employee_id=emp.employee_id,
            department_id=emp.department_id,
            name=emp.name,
            role=emp.role,
            phone=int(emp.phone) if emp.phone else None,
            availability=emp.availability.value if emp.availability else None,
            gender=emp.gender.value if emp.gender else None,
            skill=emp.skill,
            experience_years=emp.experience_years or 0,
            pending_task=pending,
            high_critical_count=high_crit_count or 0,
            total_task_completed=completed,
            department_name=dept_name,
        ))
    return results


@router.get("/{employee_id}", response_model=EmployeeResponse)
def get_employee(
    employee_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch one employee by ID."""
    return _get_scoped_employee(db, employee_id, current_user)


@router.get(
    "/{employee_id}/assignments",
    response_model=List[TaskAssignmentResponse],
)
def get_assignments_by_employee(
    employee_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch all assignments for a specific employee."""
    _get_scoped_employee(db, employee_id, current_user)
    return db.query(TaskAssignment).filter(
        TaskAssignment.employee_id == employee_id
    ).all()


@router.get(
    "/{employee_id}/checkins",
    response_model=List[WorkerCheckinResponse],
)
def get_checkins_by_employee(
    employee_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch all check-in records for a specific employee."""
    _get_scoped_employee(db, employee_id, current_user)
    return db.query(WorkerCheckin).filter(
        WorkerCheckin.employee_id == employee_id
    ).all()
