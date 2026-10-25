import hashlib
import io
import json
import zipfile
from datetime import date, datetime

import openpyxl
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from openpyxl.utils.exceptions import InvalidFileException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.models.nursing_shift_log import NursingShiftLog

router = APIRouter(prefix="/nursing-shift-logs", tags=["Admin - Nursing Shift Logs"])

REQUIRED_HEADERS = {
    "Timestamp",
    "1. Nurse Name",
    "2. Date",
    "3. Shift",
    "4. Ward / Area",
}
MAX_FILE_SIZE = 5 * 1024 * 1024
MAX_DATA_ROWS = 500


def _cell_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _parse_datetime(value, row_number, label):
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.strip())
        except ValueError:
            pass
    raise ValueError(f"Row {row_number}: {label} must be a valid date and time.")


def _parse_date(value, row_number, label):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            pass
    raise ValueError(f"Row {row_number}: {label} must be a valid date.")


def _parse_shift_row(row, header_map, row_number):
    raw = {
        header: row[index] if index < len(row) else None
        for header, index in header_map.items()
    }
    nurse_name = str(raw.get("1. Nurse Name") or "").strip()
    shift_name = str(raw.get("3. Shift") or "").strip()
    ward_area = str(raw.get("4. Ward / Area") or "").strip()
    if not nurse_name:
        raise ValueError(f"Row {row_number}: nurse name is required.")
    if not shift_name:
        raise ValueError(f"Row {row_number}: shift is required.")
    if not ward_area:
        raise ValueError(f"Row {row_number}: ward / area is required.")

    submitted_at = _parse_datetime(raw.get("Timestamp"), row_number, "Timestamp")
    shift_date = _parse_date(raw.get("2. Date"), row_number, "Date")
    answers = {header: _cell_value(value) for header, value in raw.items()}
    fingerprint = json.dumps(answers, sort_keys=True, ensure_ascii=False, default=str)

    return NursingShiftLog(
        source_hash=hashlib.sha256(fingerprint.encode("utf-8")).hexdigest(),
        submitted_at=submitted_at,
        nurse_name=nurse_name,
        shift_date=shift_date,
        shift_name=shift_name,
        ward_area=ward_area,
        answers=answers,
    )


@router.post("/import", status_code=200)
async def import_nursing_shift_logs(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    filename = file.filename or ""
    if not filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Only .xlsx Excel files are accepted.")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File size exceeds maximum limit of 5 MB.")

    try:
        workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except (InvalidFileException, zipfile.BadZipFile, OSError, ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid, corrupt, or password-protected Excel file.",
        ) from exc

    try:
        if not workbook.worksheets:
            raise HTTPException(status_code=400, detail="Workbook contains no worksheets.")
        worksheet = workbook.worksheets[0]
        rows = list(worksheet.iter_rows(values_only=True))
    finally:
        workbook.close()

    if not rows:
        raise HTTPException(status_code=400, detail="Excel sheet is empty.")

    header_map = {
        str(value).strip(): index
        for index, value in enumerate(rows[0])
        if value is not None and str(value).strip()
    }
    missing_headers = sorted(REQUIRED_HEADERS - header_map.keys())
    if missing_headers:
        raise HTTPException(
            status_code=400,
            detail={"message": "Workbook is missing required shift-log columns.", "missing_headers": missing_headers},
        )

    data_rows = [
        (row_number, row)
        for row_number, row in enumerate(rows[1:], start=2)
        if any(value is not None and str(value).strip() for value in row)
    ]
    if not data_rows:
        raise HTTPException(status_code=400, detail="Excel sheet contains no shift-log data rows.")
    if len(data_rows) > MAX_DATA_ROWS:
        raise HTTPException(
            status_code=400,
            detail=f"Workbook exceeds maximum limit of {MAX_DATA_ROWS} data rows.",
        )

    parsed_logs = []
    errors = []
    for row_number, row in data_rows:
        try:
            parsed_logs.append(_parse_shift_row(row, header_map, row_number))
        except ValueError as exc:
            errors.append(str(exc))
    if errors:
        raise HTTPException(
            status_code=400,
            detail={"message": "No rows were imported; correct the invalid rows and retry.", "errors": errors[:50]},
        )

    existing_hashes = {
        source_hash
        for (source_hash,) in db.query(NursingShiftLog.source_hash).filter(
            NursingShiftLog.source_hash.in_([log.source_hash for log in parsed_logs])
        ).all()
    }
    seen_hashes = set()
    new_logs = []
    skipped_count = 0
    for log in parsed_logs:
        if log.source_hash in existing_hashes or log.source_hash in seen_hashes:
            skipped_count += 1
            continue
        seen_hashes.add(log.source_hash)
        new_logs.append(log)

    try:
        db.add_all(new_logs)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Import conflicted with another upload. Retry; existing rows were not changed.",
        ) from exc

    return {
        "total_processed": len(data_rows),
        "imported_count": len(new_logs),
        "skipped_count": skipped_count,
    }
