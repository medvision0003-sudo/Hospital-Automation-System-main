import hashlib
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.models.nursing_shift_log import NursingShiftLog
from app.schemas.nursing_shift_log import NursingShiftLogCreate
from app.schemas.staff_automation import ShiftReportSubmissionResponse
from app.services.staff_automation_rules import execute_rules_for_report

router = APIRouter(prefix="/nursing-shift-logs", tags=["Staff Automation - Shift Reports"])


@router.post("/", response_model=ShiftReportSubmissionResponse, status_code=201)
def create_nursing_shift_log(
    data: NursingShiftLogCreate,
    db: Session = Depends(get_db),
):
    """Persist a submitted report for authorized staff and supervisors."""
    answers = dict(data.answers)
    answers.setdefault("1. Nurse Name", data.nurse_name)
    answers.setdefault("2. Date", data.shift_date.isoformat())
    answers.setdefault("3. Shift", data.shift_name)
    answers.setdefault("4. Ward / Area", data.ward_area)
    submitted_at = data.submitted_at or datetime.now()
    if not answers.get("Timestamp"):
        answers["Timestamp"] = submitted_at.isoformat()
    fingerprint = json.dumps(
        {
            "nurse_name": data.nurse_name,
            "shift_date": data.shift_date.isoformat(),
            "shift_name": data.shift_name,
            "ward_area": data.ward_area,
            "answers": {key: value for key, value in answers.items() if key != "Timestamp"},
        },
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    record = NursingShiftLog(
        source_hash=hashlib.sha256(fingerprint.encode("utf-8")).hexdigest(),
        submitted_at=submitted_at,
        nurse_name=data.nurse_name,
        shift_date=data.shift_date,
        shift_name=data.shift_name,
        ward_area=data.ward_area,
        answers=answers,
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="An identical shift report has already been submitted.",
        ) from exc
    db.refresh(record)
    executions = execute_rules_for_report(db, record)
    return {
        **{
            "log_id": record.log_id,
            "submitted_at": record.submitted_at,
            "nurse_name": record.nurse_name,
            "shift_date": record.shift_date,
            "shift_name": record.shift_name,
            "ward_area": record.ward_area,
            "answers": record.answers,
        },
        "automation_executions": executions,
    }
