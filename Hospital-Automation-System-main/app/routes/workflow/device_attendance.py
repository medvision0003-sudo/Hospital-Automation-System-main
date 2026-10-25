import hashlib
import hmac
import secrets
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents.event_agent import publish_event
from app.core.dependencies import require_roles
from app.database.connection import get_db
from app.models.attendance_device import AttendanceDevice
from app.models.employee import Employee
from app.models.enums import CheckinStatusEnum, HospitalEventEnum, UserRoleEnum
from app.models.worker_checkin import WorkerCheckin


router = APIRouter(prefix="/device-attendance", tags=["Device Attendance"])
admin_router = APIRouter(
    prefix="/admin/attendance-devices",
    tags=["Admin - Attendance Devices"],
    dependencies=[Depends(require_roles([UserRoleEnum.ADMIN]))],
)


class DeviceRegistration(BaseModel):
    device_id: str = Field(min_length=1, max_length=100)
    employee_id: int = Field(gt=0)


class DeviceRegistrationResponse(BaseModel):
    device_id: str
    employee_id: int
    device_token: str
    is_active: bool


class AttendanceEvent(BaseModel):
    device_id: str = Field(min_length=1, max_length=100)
    employee_id: int = Field(gt=0)
    event: Literal["CHECK_IN", "CHECK_OUT"]
    occurred_at: Optional[datetime] = None


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _authenticate_device(
    db: Session,
    device_id: str,
    device_token: Optional[str],
) -> AttendanceDevice:
    device = db.query(AttendanceDevice).filter(
        AttendanceDevice.device_id == device_id
    ).first()
    if (
        device is None
        or not device.is_active
        or not device_token
        or not hmac.compare_digest(device.token_hash, _hash_token(device_token))
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unknown device or invalid device credentials",
        )
    return device


def _normalize_datetime(value: Optional[datetime]) -> datetime:
    timestamp = value or datetime.now().astimezone()
    if timestamp.tzinfo is not None:
        timestamp = timestamp.astimezone().replace(tzinfo=None)
    return timestamp


@admin_router.post("/", response_model=DeviceRegistrationResponse, status_code=201)
def register_device(data: DeviceRegistration, db: Session = Depends(get_db)):
    if db.query(Employee.employee_id).filter(
        Employee.employee_id == data.employee_id
    ).first() is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    if db.query(AttendanceDevice).filter(
        AttendanceDevice.device_id == data.device_id
    ).first():
        raise HTTPException(status_code=409, detail="Device ID already registered")

    token = secrets.token_urlsafe(32)
    device = AttendanceDevice(
        device_id=data.device_id,
        employee_id=data.employee_id,
        token_hash=_hash_token(token),
    )
    db.add(device)
    db.commit()
    return DeviceRegistrationResponse(
        device_id=device.device_id,
        employee_id=device.employee_id,
        device_token=token,
        is_active=device.is_active,
    )


@admin_router.get("/")
def list_devices(db: Session = Depends(get_db)):
    devices = db.query(AttendanceDevice).order_by(
        AttendanceDevice.device_id
    ).all()
    return [
        {
            "device_id": device.device_id,
            "employee_id": device.employee_id,
            "is_active": device.is_active,
            "created_at": device.created_at,
            "last_seen_at": device.last_seen_at,
        }
        for device in devices
    ]


@admin_router.delete("/{device_id}", status_code=204)
def revoke_device(device_id: str, db: Session = Depends(get_db)):
    device = db.query(AttendanceDevice).filter(
        AttendanceDevice.device_id == device_id
    ).first()
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    device.is_active = False
    db.commit()


@router.post("/event")
def receive_attendance_event(
    data: AttendanceEvent,
    x_device_token: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    device = _authenticate_device(db, data.device_id, x_device_token)
    if device.employee_id != data.employee_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Device is not registered to this employee",
        )

    employee = db.query(Employee).filter(
        Employee.employee_id == data.employee_id
    ).first()
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")

    timestamp = _normalize_datetime(data.occurred_at)
    device.last_seen_at = datetime.now()

    if data.event == "CHECK_IN":
        latest_checkin = (
            db.query(WorkerCheckin)
            .filter(WorkerCheckin.employee_id == employee.employee_id)
            .order_by(WorkerCheckin.checkin_time.desc())
            .first()
        )
        active_checkin = db.query(WorkerCheckin).filter(
            WorkerCheckin.employee_id == employee.employee_id,
            WorkerCheckin.status == CheckinStatusEnum.CHECKED_IN,
        ).first()
        if active_checkin:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Employee is already checked in",
            )
        if latest_checkin and latest_checkin.checkout_time:
            if timestamp <= latest_checkin.checkout_time:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Attendance event timestamp is not newer than the latest check-out",
                )
        result = publish_event(
            HospitalEventEnum.WORKER_CHECKED_IN,
            {
                "employee_id": employee.employee_id,
                "device_id": device.device_id,
                "occurred_at": timestamp.isoformat(),
                "trigger_source": "ATTENDANCE_DEVICE",
            },
            db,
        )
        workflow_status = result.get("status")
        if getattr(workflow_status, "value", workflow_status) == "FAILED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=result.get("reason", "Check-in workflow could not be completed"),
            )
        db.commit()
        return {"event": data.event, "employee_id": employee.employee_id, "result": result}

    active_checkin = db.query(WorkerCheckin).filter(
        WorkerCheckin.employee_id == employee.employee_id,
        WorkerCheckin.status == CheckinStatusEnum.CHECKED_IN,
    ).order_by(WorkerCheckin.checkin_time.desc()).first()
    if active_checkin is None or active_checkin.device_id != device.device_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No active check-in exists for this device",
        )

    result = publish_event(
        HospitalEventEnum.WORKER_CHECKED_OUT,
        {
            "employee_id": employee.employee_id,
            "device_id": device.device_id,
            "occurred_at": timestamp.isoformat(),
            "trigger_source": "ATTENDANCE_DEVICE",
        },
        db,
    )
    workflow_status = result.get("status")
    if getattr(workflow_status, "value", workflow_status) == "FAILED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=result.get("reason", "Check-out workflow could not be completed"),
        )
    db.commit()
    return {"event": data.event, "employee_id": employee.employee_id, "result": result}
