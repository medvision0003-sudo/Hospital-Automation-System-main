from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.models.attendance_device import AttendanceDevice
from app.models.automation_rule import AutomationRule
from app.models.employee import Employee
from app.models.enums import CheckinStatusEnum
from app.models.event_log import EventLog
from app.models.shift_roster import ShiftRoster
from app.models.supervisor_task_request import SupervisorTaskRequest
from app.models.task_assignment import TaskAssignment
from app.models.task_proof import TaskProof
from app.models.user import User
from app.models.whatsapp_message import WhatsAppMessage
from app.models.worker_memory import WorkerMemory
from app.models.worker_checkin import WorkerCheckin
from app.schemas.employee import EmployeeCreate, EmployeeUpdate, EmployeeResponse

router = APIRouter(prefix="/employees", tags=["Admin - Employees"])


def _reassign_employee_references(
    db: Session,
    source_id: int,
    target: Employee,
) -> dict:
    target_id = target.employee_id
    reassignments = (
        (AttendanceDevice, AttendanceDevice.employee_id),
        (AutomationRule, AutomationRule.approved_employee_id),
        (EventLog, EventLog.employee_id),
        (TaskAssignment, TaskAssignment.employee_id),
        (TaskProof, TaskProof.employee_id),
        (SupervisorTaskRequest, SupervisorTaskRequest.supervisor_id),
        (WhatsAppMessage, WhatsAppMessage.employee_id),
        (User, User.employee_id),
    )
    counts = {}
    for model, column in reassignments:
        counts[model.__tablename__] = db.query(model).filter(
            column == source_id
        ).update(
            {column: target_id},
            synchronize_session=False,
        )

    source_rosters = db.query(ShiftRoster).filter(
        ShiftRoster.employee_id == source_id
    ).all()
    for source_roster in source_rosters:
        target_roster = db.query(ShiftRoster).filter(
            ShiftRoster.employee_id == target_id,
            ShiftRoster.shift_id == source_roster.shift_id,
            ShiftRoster.work_date == source_roster.work_date,
        ).first()
        if target_roster:
            raise HTTPException(
                status_code=409,
                detail=(
                    "These employees have the same shift on the same date. "
                    "Resolve the duplicate roster entry before merging."
                ),
            )
        source_roster.employee = target
    counts[ShiftRoster.__tablename__] = len(source_rosters)

    source_checkins = db.query(WorkerCheckin).filter(
        WorkerCheckin.employee_id == source_id
    ).all()
    target_checkins = db.query(WorkerCheckin).filter(
        WorkerCheckin.employee_id == target_id
    ).all()
    active_checkins = sorted(
        [
            record
            for record in source_checkins + target_checkins
            if record.status == CheckinStatusEnum.CHECKED_IN
            and record.checkout_time is None
        ],
        key=lambda record: record.checkin_time,
    )
    for earlier, later in zip(active_checkins, active_checkins[1:]):
        earlier.status = CheckinStatusEnum.CHECKED_OUT
        earlier.checkout_time = later.checkin_time
    for checkin in source_checkins:
        checkin.employee = target
    counts[WorkerCheckin.__tablename__] = len(source_checkins)

    source_memory = db.get(WorkerMemory, source_id)
    target_memory = db.get(WorkerMemory, target_id)
    if source_memory:
        if target_memory:
            for field in ("pending_task", "total_task_completed"):
                target_value = getattr(target_memory, field)
                source_value = getattr(source_memory, field)
                if target_value is not None or source_value is not None:
                    setattr(
                        target_memory,
                        field,
                        (target_value or 0) + (source_value or 0),
                    )
            if source_memory.last_updated and (
                target_memory.last_updated is None
                or source_memory.last_updated > target_memory.last_updated
            ):
                target_memory.last_updated = source_memory.last_updated
        else:
            source_memory.employee_id = target_id
    counts[WorkerMemory.__tablename__] = int(source_memory is not None)

    return counts


@router.post("/", response_model=EmployeeResponse, status_code=201)
def create_employee(data: EmployeeCreate, db: Session = Depends(get_db)):
    """Create a new employee and initialize worker memory."""
    new_employee = Employee(**data.model_dump())
    db.add(new_employee)
    db.commit()
    db.refresh(new_employee)

    memory = WorkerMemory(employee_id=new_employee.employee_id)
    db.add(memory)
    db.commit()

    return new_employee


@router.post("/{source_id}/merge-into/{target_id}")
def merge_employee(
    source_id: int,
    target_id: int,
    db: Session = Depends(get_db),
):
    """Merge a duplicate employee into a canonical employee and retain linked history."""
    if source_id == target_id:
        raise HTTPException(status_code=400, detail="Cannot merge an employee into itself.")

    source = db.query(Employee).filter(Employee.employee_id == source_id).first()
    target = db.query(Employee).filter(Employee.employee_id == target_id).first()
    if not source or not target:
        raise HTTPException(status_code=404, detail="Source or target employee not found.")
    if source.name.strip().casefold() != target.name.strip().casefold():
        raise HTTPException(
            status_code=409,
            detail="Only employees with the same normalized name can be merged.",
        )
    if source.department_id != target.department_id:
        raise HTTPException(
            status_code=409,
            detail="Employees must belong to the same department before merging.",
        )

    source_user = db.query(User).filter(User.employee_id == source_id).first()
    target_user = db.query(User).filter(User.employee_id == target_id).first()
    if source_user and target_user:
        raise HTTPException(
            status_code=409,
            detail=(
                "Both employees have linked user accounts. "
                "Resolve the account ownership before merging."
            ),
        )

    try:
        counts = _reassign_employee_references(db, source_id, target)
        db.flush()
        db.delete(source)
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "message": f"Employee {source_id} merged into employee {target_id}.",
        "source_employee_id": source_id,
        "target_employee_id": target_id,
        "reassigned_records": counts,
    }


@router.put("/{employee_id}", response_model=EmployeeResponse)
def update_employee(
    employee_id: int,
    data: EmployeeUpdate,
    db: Session = Depends(get_db),
):
    """Update an existing employee (partial update)."""
    employee = db.query(Employee).filter(
        Employee.employee_id == employee_id
    ).first()

    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(employee, field, value)

    db.commit()
    db.refresh(employee)
    return employee


@router.delete("/{employee_id}", status_code=200)
def delete_employee(employee_id: int, db: Session = Depends(get_db)):
    """Delete an employee by ID."""
    employee = db.query(Employee).filter(
        Employee.employee_id == employee_id
    ).first()

    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    db.delete(employee)
    db.commit()
    return {"message": f"Employee {employee_id} deleted successfully"}
