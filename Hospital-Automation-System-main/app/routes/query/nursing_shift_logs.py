from collections import Counter
from datetime import date
from statistics import mean
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.models.nursing_shift_log import NursingShiftLog
from app.schemas.nursing_shift_log import NursingShiftLogResponse

router = APIRouter(prefix="/nursing-shift-logs", tags=["Query - Nursing Shift Logs"])

PATIENT_COUNT_KEY = "5. Total Patients Under Your Care (Enter a number)"
EMERGENCY_KEY = "16. Any Emergency During Shift?"
MEDICATION_KEY = "11. Were All Medicines Given on Time?"
EQUIPMENT_KEY = "20. Any Equipment Malfunction?"
HANDOVER_KEY = "22. Was Proper Handover Given?"
STAFFING_KEY = "25. Staffing Status"
DELAY_REASON_KEY = "12. Reason for Medication Delay (Select all that apply)"


def _percentage(numerator, denominator):
    return round(numerator / denominator * 100, 1) if denominator else 0


@router.get("/", response_model=List[NursingShiftLogResponse])
def get_nursing_shift_logs(
    nurse_name: Optional[str] = Query(None, min_length=1),
    shift_date: Optional[date] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(NursingShiftLog)
    if nurse_name:
        query = query.filter(NursingShiftLog.nurse_name.ilike(f"%{nurse_name.strip()}%"))
    if shift_date:
        query = query.filter(NursingShiftLog.shift_date == shift_date)
    return query.order_by(NursingShiftLog.shift_date.desc(), NursingShiftLog.log_id.desc()).offset(offset).limit(limit).all()


@router.get("/analytics")
def get_nursing_shift_log_analytics(db: Session = Depends(get_db)):
    """Calculate historical-only metrics from preserved nursing shift reports."""
    records = db.query(NursingShiftLog).all()
    total = len(records)
    patient_counts = []
    wards = Counter()
    shifts = Counter()
    emergency_count = 0
    emergency_observations = 0
    medication_delay_count = 0
    medication_observations = 0
    equipment_issue_count = 0
    equipment_observations = 0
    handover_issue_count = 0
    handover_observations = 0
    staffing_counts = Counter()
    medication_delay_reasons = Counter()

    for record in records:
        answers = record.answers or {}
        try:
            patient_count = int(answers.get(PATIENT_COUNT_KEY))
            if patient_count >= 0:
                patient_counts.append(patient_count)
        except (TypeError, ValueError):
            pass

        wards[record.ward_area] += 1
        shifts[record.shift_name] += 1
        emergency_value = str(answers.get(EMERGENCY_KEY) or "").strip().casefold()
        if emergency_value in {"yes", "no"}:
            emergency_observations += 1
            emergency_count += int(emergency_value == "yes")
        medication_value = str(answers.get(MEDICATION_KEY) or "").strip().casefold()
        medication_delay = medication_value == "no"
        if medication_value in {"yes", "no"}:
            medication_observations += 1
            medication_delay_count += int(medication_delay)

        equipment_value = str(answers.get(EQUIPMENT_KEY) or "").strip().casefold()
        if equipment_value in {"yes", "no"}:
            equipment_observations += 1
            equipment_issue_count += int(equipment_value == "yes")

        handover_value = str(answers.get(HANDOVER_KEY) or "").strip().casefold()
        if handover_value in {"yes", "no"}:
            handover_observations += 1
            handover_issue_count += int(handover_value == "no")

        staffing_status = str(answers.get(STAFFING_KEY) or "").strip()
        if staffing_status:
            staffing_counts[staffing_status] += 1
        if medication_delay:
            reasons = str(answers.get(DELAY_REASON_KEY) or "").strip()
            if reasons:
                medication_delay_reasons[reasons] += 1

    return {
        "data_source": "historical_nursing_shift_logs",
        "total_records": total,
        "average_patients_per_shift": round(mean(patient_counts), 2) if patient_counts else None,
        "emergency_occurrences": emergency_count,
        "emergency_observations": emergency_observations,
        "emergency_rate_percent": _percentage(emergency_count, emergency_observations),
        "medication_delay_occurrences": medication_delay_count,
        "medication_observations": medication_observations,
        "medication_delay_rate_percent": _percentage(medication_delay_count, medication_observations),
        "equipment_issue_occurrences": equipment_issue_count,
        "equipment_observations": equipment_observations,
        "equipment_issue_rate_percent": _percentage(equipment_issue_count, equipment_observations),
        "handover_issue_occurrences": handover_issue_count,
        "handover_observations": handover_observations,
        "handover_issue_rate_percent": _percentage(handover_issue_count, handover_observations),
        "records_by_ward": [
            {"ward_area": ward, "records": count}
            for ward, count in sorted(wards.items())
        ],
        "records_by_shift": [
            {"shift_name": shift, "records": count}
            for shift, count in sorted(shifts.items())
        ],
        "staffing_status_counts": dict(sorted(staffing_counts.items())),
        "medication_delay_reason_counts": dict(sorted(medication_delay_reasons.items())),
    }
