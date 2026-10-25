from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents.event_agent import publish_event
from app.database.connection import get_db
from app.models.enums import CheckinStatusEnum, HospitalEventEnum
from app.models.worker_checkin import WorkerCheckin
from app.schemas.worker_checkin import (
    WorkerCheckinCreate,
    WorkerCheckinUpdate,
    WorkerCheckinResponse,
)

router = APIRouter(tags=["Admin - Check-ins"])


def _publish_manual_attendance_event(
    event_type: HospitalEventEnum,
    employee_id: int,
    occurred_at: datetime,
    db: Session,
):
    result = publish_event(
        event_type,
        {
            "employee_id": employee_id,
            "occurred_at": occurred_at.isoformat(),
            "trigger_source": "MANUAL_OVERRIDE",
        },
        db,
    )
    workflow_status = result.get("status")
    if getattr(workflow_status, "value", workflow_status) == "FAILED":
        raise HTTPException(
            status_code=409,
            detail=result.get("reason", "Attendance workflow could not be completed"),
        )
    return result


@router.post("/checkins", response_model=WorkerCheckinResponse, status_code=201)
def create_checkin(data: WorkerCheckinCreate, db: Session = Depends(get_db)):
    """Record demo/manual attendance through the shared event workflow."""
    if data.status not in (
        CheckinStatusEnum.CHECKED_IN,
        CheckinStatusEnum.CHECKED_OUT,
    ):
        raise HTTPException(
            status_code=400,
            detail="Manual attendance can only record check-in or check-out events.",
        )

    _publish_manual_attendance_event(
        HospitalEventEnum.WORKER_CHECKED_IN,
        data.employee_id,
        data.checkin_time,
        db,
    )
    checkin_time = data.checkin_time
    if checkin_time.tzinfo is not None:
        checkin_time = checkin_time.astimezone().replace(tzinfo=None)
    record = (
        db.query(WorkerCheckin)
        .filter(
            WorkerCheckin.employee_id == data.employee_id,
            WorkerCheckin.checkin_time == checkin_time,
        )
        .first()
    )
    if record is None:
        raise HTTPException(status_code=409, detail="Check-in workflow created no attendance record.")

    checkout_time = data.checkout_time
    if data.status == CheckinStatusEnum.CHECKED_OUT or checkout_time:
        _publish_manual_attendance_event(
            HospitalEventEnum.WORKER_CHECKED_OUT,
            data.employee_id,
            checkout_time or datetime.now(),
            db,
        )
        db.refresh(record)
    return record


@router.put("/checkins", response_model=WorkerCheckinResponse)
def update_checkin(
    device_id: str,
    checkin_time: datetime,
    data: WorkerCheckinUpdate,
    db: Session = Depends(get_db),
):
    """Check out a manually recorded attendance entry through the event workflow."""
    record = db.query(WorkerCheckin).filter(
        WorkerCheckin.device_id == device_id,
        WorkerCheckin.checkin_time == checkin_time,
    ).first()

    if not record:
        raise HTTPException(status_code=404, detail="Check-in record not found")

    update_fields = data.model_dump(exclude_unset=True)
    if not device_id.startswith(("MANUAL_OVERRIDE_", "CHECKIN_")):
        raise HTTPException(
            status_code=400,
            detail="Device attendance records can only be changed by the registered attendance device.",
        )
    if (
        update_fields.get("employee_id") not in (None, record.employee_id)
        or update_fields.get("status") not in (None, CheckinStatusEnum.CHECKED_OUT)
    ):
        raise HTTPException(
            status_code=400,
            detail="Manual attendance updates may only record check-out.",
        )
    checkout_time = update_fields.get("checkout_time")
    if checkout_time is None and update_fields.get("status") != CheckinStatusEnum.CHECKED_OUT:
        raise HTTPException(status_code=400, detail="A check-out time or CHECKED_OUT status is required.")
    _publish_manual_attendance_event(
        HospitalEventEnum.WORKER_CHECKED_OUT,
        record.employee_id,
        checkout_time or datetime.now(),
        db,
    )
    db.refresh(record)
    return record
