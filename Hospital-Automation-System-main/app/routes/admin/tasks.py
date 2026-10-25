import io
from datetime import datetime, time
import openpyxl
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database.connection import get_db
from app.models.task_master import TaskMaster
from app.models.department import Department
from app.models.enums import PriorityEnum, TaskStatusEnum, TaskTypeEnum
from app.schemas.task_master import TaskCreate, TaskUpdate, TaskResponse
from app.utils.standardize import standardize_string, standardize_skills

router = APIRouter(prefix="/tasks", tags=["Admin - Tasks"])


def _parse_excel_time(value, field_name):
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, datetime):
        return value.time().replace(second=0, microsecond=0)
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    if isinstance(value, (int, float)):
        if not 0 <= value < 1:
            raise ValueError(f"Invalid {field_name}; expected a time of day.")
        minutes = round(value * 24 * 60) % (24 * 60)
        return time(minutes // 60, minutes % 60)
    try:
        return time.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise ValueError(
            f"Invalid {field_name} '{value}'; expected HH:MM."
        ) from exc


def _parse_excel_boolean(value, field_name):
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().casefold()
    if normalized in {"true", "yes", "1", "required"}:
        return True
    if normalized in {"false", "no", "0", "optional"}:
        return False
    raise ValueError(
        f"Invalid {field_name} '{value}'; expected TRUE/FALSE."
    )


@router.post("/bulk-upload", status_code=200)
async def bulk_upload_tasks(file: UploadFile = File(...), db: Session = Depends(get_db)):
    filename = file.filename or ""
    if not filename.lower().endswith(".xlsx"):
        raise HTTPException(
            status_code=400,
            detail="Only .xlsx Excel files are accepted."
        )

    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail="File size exceeds maximum limit of 5 MB."
        )

    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid, corrupt, or password-protected Excel file."
        )

    try:
        if not wb.worksheets:
            raise HTTPException(
                status_code=400,
                detail="Workbook contains no worksheets."
            )
        ws = wb.worksheets[0]
        rows = list(ws.iter_rows(values_only=True))
    finally:
        wb.close()

    if not rows or len(rows) <= 1:
        raise HTTPException(
            status_code=400,
            detail="Excel sheet is empty or contains no data rows."
        )

    if len(rows) - 1 > 500:
        raise HTTPException(
            status_code=400,
            detail="Workbook exceeds maximum limit of 500 data rows."
        )

    header_row = rows[0]
    header_map = {}
    for idx, val in enumerate(header_row):
        if val is not None:
            clean_hdr = str(val).strip().lower()
            header_map[clean_hdr] = idx

    has_dept_col = "department_id" in header_map or "department_name" in header_map
    has_task_name_col = "task_name" in header_map
    has_task_type_col = "task_type" in header_map

    if not (has_dept_col and has_task_name_col and has_task_type_col):
        raise HTTPException(
            status_code=400,
            detail="Excel header missing required fields (department_id/department_name, task_name, task_type)."
        )

    departments = db.query(Department).all()
    dept_id_map = {d.department_id: d.department_id for d in departments}
    dept_name_map = {d.department_name.strip().lower(): d.department_id for d in departments}

    existing_tasks = db.query(TaskMaster.department_id, TaskMaster.task_name).all()
    existing_set = {
        (t.department_id, standardize_string(t.task_name)): True
        for t in existing_tasks if t.department_id and t.task_name
    }

    seen_in_workbook = set()
    total_processed = 0
    imported_count = 0
    skipped_count = 0
    failed_count = 0
    errors = []
    skips = []
    new_task_models = []

    for row_idx, row_values in enumerate(rows[1:], start=2):
        if not row_values or all(v is None or str(v).strip() == "" for v in row_values):
            continue

        total_processed += 1

        raw_dept_id = row_values[header_map["department_id"]] if "department_id" in header_map else None
        raw_dept_name = row_values[header_map["department_name"]] if "department_name" in header_map else None
        raw_task_name = row_values[header_map["task_name"]] if "task_name" in header_map else None
        raw_desc = row_values[header_map["description"]] if "description" in header_map else None
        raw_priority = row_values[header_map["priority_category"]] if "priority_category" in header_map else None
        raw_est_time = row_values[header_map["estimated_time"]] if "estimated_time" in header_map else None
        raw_task_type = row_values[header_map["task_type"]] if "task_type" in header_map else None
        raw_role = row_values[header_map["required_role"]] if "required_role" in header_map else None
        raw_skill = row_values[header_map["required_skill"]] if "required_skill" in header_map else None
        raw_state = row_values[header_map["task_state"]] if "task_state" in header_map else None
        raw_start_time = row_values[header_map["suggested_start_time"]] if "suggested_start_time" in header_map else None
        raw_due_time = row_values[header_map["due_time"]] if "due_time" in header_map else None
        raw_requires_proof = row_values[header_map["requires_proof"]] if "requires_proof" in header_map else None

        resolved_dept_id = None
        if raw_dept_id is not None and str(raw_dept_id).strip() != "":
            raw_id_str = str(raw_dept_id).strip()
            if raw_id_str.isdigit():
                parsed_id = int(raw_id_str)
                if parsed_id in dept_id_map:
                    resolved_dept_id = parsed_id
            if resolved_dept_id is None and raw_id_str.lower() in dept_name_map:
                resolved_dept_id = dept_name_map[raw_id_str.lower()]

        if resolved_dept_id is None and raw_dept_name is not None and str(raw_dept_name).strip() != "":
            name_str = str(raw_dept_name).strip().lower()
            if name_str in dept_name_map:
                resolved_dept_id = dept_name_map[name_str]

        if resolved_dept_id is None:
            dept_val_repr = raw_dept_id if raw_dept_id is not None else raw_dept_name
            errors.append({"row": row_idx, "reason": f"Unknown department specified ('{dept_val_repr}')"})
            failed_count += 1
            continue

        if not raw_task_name or str(raw_task_name).strip() == "":
            errors.append({"row": row_idx, "reason": "Task name is required"})
            failed_count += 1
            continue
        clean_name = standardize_string(str(raw_task_name))

        if not raw_task_type or str(raw_task_type).strip() == "":
            errors.append({"row": row_idx, "reason": "Task type is required"})
            failed_count += 1
            continue
        clean_type_str = str(raw_task_type).strip().upper()
        if clean_type_str not in ["RECURRING", "EVENT_TEMPLATE"]:
            errors.append({"row": row_idx, "reason": f"Invalid task_type '{raw_task_type}'. Must be RECURRING or EVENT_TEMPLATE"})
            failed_count += 1
            continue
        clean_type = TaskTypeEnum[clean_type_str]

        clean_prio = PriorityEnum.MEDIUM
        if raw_priority is not None and str(raw_priority).strip() != "":
            prio_str = str(raw_priority).strip().upper()
            if prio_str not in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]:
                errors.append({"row": row_idx, "reason": f"Invalid priority_category '{raw_priority}'. Must be LOW, MEDIUM, HIGH, or CRITICAL"})
                failed_count += 1
                continue
            clean_prio = PriorityEnum[prio_str]

        clean_state = TaskStatusEnum.ACTIVE
        if raw_state is not None and str(raw_state).strip() != "":
            state_str = str(raw_state).strip().upper()
            if state_str not in ["ACTIVE", "INACTIVE"]:
                errors.append({"row": row_idx, "reason": f"Invalid task_state '{raw_state}'. Must be ACTIVE or INACTIVE"})
                failed_count += 1
                continue
            clean_state = TaskStatusEnum[state_str]

        clean_time = None
        if raw_est_time is not None and str(raw_est_time).strip() != "":
            try:
                t_val = int(raw_est_time)
                if t_val < 1 or t_val > 1440:
                    raise ValueError()
                clean_time = t_val
            except (ValueError, TypeError):
                errors.append({"row": row_idx, "reason": f"Invalid estimated_time '{raw_est_time}'. Must be an integer between 1 and 1440 minutes"})
                failed_count += 1
                continue

        dup_key = (resolved_dept_id, clean_name)
        if dup_key in existing_set or dup_key in seen_in_workbook:
            skips.append({"row": row_idx, "reason": f"Duplicate task '{clean_name}' in department {resolved_dept_id}"})
            skipped_count += 1
            continue

        seen_in_workbook.add(dup_key)

        clean_desc = str(raw_desc).strip() if raw_desc is not None and str(raw_desc).strip() != "" else None
        clean_skill = standardize_skills(str(raw_skill)) if raw_skill is not None and str(raw_skill).strip() != "" else None

        try:
            start_time = _parse_excel_time(raw_start_time, "suggested_start_time")
            due_time = _parse_excel_time(raw_due_time, "due_time")
            requires_proof = _parse_excel_boolean(raw_requires_proof, "requires_proof")
            task_schema = TaskCreate(
                department_id=resolved_dept_id,
                task_name=clean_name,
                description=clean_desc,
                priority_category=clean_prio,
                estimated_time=clean_time,
                task_state=clean_state,
                task_type=clean_type,
                required_role=standardize_string(str(raw_role)) if raw_role is not None else None,
                required_skill=clean_skill,
                suggested_start_time=start_time,
                due_time=due_time,
                requires_proof=requires_proof if requires_proof is not None else False,
            )
        except (ValueError, TypeError) as p_err:
            errors.append({"row": row_idx, "reason": f"Validation error: {str(p_err)}"})
            failed_count += 1
            continue

        new_task = TaskMaster(**task_schema.model_dump())
        new_task_models.append(new_task)
        imported_count += 1

    if new_task_models:
        try:
            db.add_all(new_task_models)
            db.commit()
        except Exception as db_err:
            db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Database transaction failure: {str(db_err)}"
            )

    return {
        "total_processed": total_processed,
        "imported_count": imported_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "errors": errors,
        "skips": skips
    }


@router.post("/", response_model=TaskResponse, status_code=201)
def create_task(task_data: TaskCreate, db: Session = Depends(get_db)):
    task_dict = task_data.model_dump()

    new_task = TaskMaster(**task_dict)
    db.add(new_task)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Task already exists in this department"
        )
    db.refresh(new_task)

    return new_task


@router.put("/{task_id}", response_model=TaskResponse)
def update_task(task_id: int, task_data: TaskUpdate, db: Session = Depends(get_db)):
    task = db.query(TaskMaster).filter(
        TaskMaster.task_id == task_id
    ).first()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    update_fields = task_data.model_dump(exclude_unset=True)
    for key, value in update_fields.items():
        setattr(task, key, value)

    db.commit()
    db.refresh(task)

    return task


@router.delete("/{task_id}", status_code=200)
def delete_task(task_id: int, db: Session = Depends(get_db)):
    task = db.query(TaskMaster).filter(
        TaskMaster.task_id == task_id
    ).first()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    db.delete(task)
    db.commit()
    return {"message": f"Task {task_id} deleted successfully"}
