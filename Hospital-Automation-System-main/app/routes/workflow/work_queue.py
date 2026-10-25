"""
Work Queue Workflow Routes

Provides the proof submission endpoint for task completion verification.
Workers submit proof (file upload or image path) which triggers the
Task Verification Agent via the transactional outbox.
"""

import uuid
from pathlib import Path, PurePosixPath
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.models.department_work_queue import DepartmentWorkQueue
from app.models.task_proof import TaskProof
from app.models.task_assignment import TaskAssignment
from app.models.enums import (
    AssignmentStatusEnum,
    WorkQueueStatusEnum,
    TaskProofStatusEnum,
)
from app.services.outbox_dispatcher import create_outbox_event, signal_outbox_wake


router = APIRouter(prefix="/work-queue", tags=["Workflow - Work Queue"])

# Allowed file extensions for proof uploads
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
# Local uploads path
UPLOAD_BASE_DIR = Path("uploads")
# Maximum upload size in bytes (10 MB)
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _validate_proof_image_path(path: str) -> None:
    """Validate a text proof_image_path using POSIX-style normalized checks.

    Rejects absolute paths, backslashes, path traversal, URLs, and any
    path not starting with the internal uploads/ prefix.
    """
    if path.startswith("/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="proof_image_path must be a relative path (no leading /)",
        )
    if "\\" in path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="proof_image_path must not contain backslashes",
        )
    if ".." in PurePosixPath(path).parts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="proof_image_path must not contain path traversal (..)",
        )
    if path.lower().startswith(("http://", "https://")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="proof_image_path must not be a URL",
        )
    if not path.startswith("uploads/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="proof_image_path must start with uploads/",
        )
    # Enforce image-only extensions on text paths using the same ALLOWED_EXTENSIONS
    suffix = PurePosixPath(path).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"File type '{suffix}' is not allowed. "
                f"Accepted: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            ),
        )


@router.post("/{work_id}/submit-proof", status_code=status.HTTP_202_ACCEPTED)
async def submit_proof(
    work_id: int,
    proof_image_path: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    """Submit proof of task completion for verification.

    Requires either proof_image_path (text path) or file (upload).
    If both are missing, returns 400.
    """

    # Validate that at least one proof source is provided
    if not proof_image_path and not file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either proof_image_path or file must be provided",
        )

    # Validate proof_image_path if provided (POSIX-style normalized checks)
    if proof_image_path:
        _validate_proof_image_path(proof_image_path)

    # File upload path: delegate to shared service
    if file:
        content = await file.read()
        safe_name = Path(file.filename).name if file.filename else "upload.jpg"

        from app.services.task_proof_service import save_task_proof
        result = save_task_proof(
            db=db,
            work_id=work_id,
            file_content=content,
            filename=safe_name,
            commit=True,
        )
        return {
            "status": "Accepted",
            "work_id": work_id,
            "proof_id": result["proof_id"],
            "proof_image_path": result["proof_image_path"],
            "message": "Proof submitted for verification via outbox",
        }

    # Text-path-only submission (no file upload)
    work_item = (
        db.query(DepartmentWorkQueue)
        .filter(DepartmentWorkQueue.work_id == work_id)
        .first()
    )
    if not work_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Work item {work_id} not found",
        )

    if work_item.queue_status != WorkQueueStatusEnum.ASSIGNED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Work item {work_id} is not ASSIGNED "
                f"(current: {work_item.queue_status.value})"
            ),
        )

    active_assignment = (
        db.query(TaskAssignment)
        .filter(
            TaskAssignment.work_id == work_id,
            TaskAssignment.assignment_status.in_([
                AssignmentStatusEnum.ASSIGNED,
                AssignmentStatusEnum.IN_PROGRESS,
            ]),
        )
        .order_by(TaskAssignment.assigned_at.desc())
        .first()
    )
    if active_assignment is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Work item has no active employee assignment",
        )

    proof_file_path = None
    if proof_image_path:
        proof_file_path = (UPLOAD_BASE_DIR / proof_image_path.removeprefix("uploads/")).resolve()
        upload_root = UPLOAD_BASE_DIR.resolve()
        if upload_root not in proof_file_path.parents or not proof_file_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Proof image file not found",
            )

    proof_record = TaskProof(
        work_id=work_id,
        employee_id=active_assignment.employee_id,
        proof_image_path=proof_image_path,
        verification_status=TaskProofStatusEnum.PENDING,
        verification_attempts=db.query(TaskProof).filter(
            TaskProof.work_id == work_id
        ).count() + 1,
    )
    db.add(proof_record)
    db.flush()

    create_outbox_event(
        db,
        event_type="TASK_PROOF_SUBMITTED",
        payload={
            "work_id": work_id,
            "proof_id": proof_record.proof_id,
            "proof_image_path": proof_image_path,
        },
    )

    db.commit()
    signal_outbox_wake()

    return {
        "status": "Accepted",
        "work_id": work_id,
        "proof_id": proof_record.proof_id,
        "proof_image_path": proof_image_path,
        "message": "Proof submitted for verification via outbox",
    }
