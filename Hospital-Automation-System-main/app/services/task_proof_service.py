"""
Task Proof Service

Shared service for saving task completion proofs from both the
REST API upload endpoint and the WhatsApp inbound image handler.
Accepts raw bytes and filename; the caller reads the file/upload.
"""

import uuid
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.department_work_queue import DepartmentWorkQueue
from app.models.task_assignment import TaskAssignment
from app.models.task_proof import TaskProof
from app.models.enums import (
    AssignmentStatusEnum,
    WorkQueueStatusEnum,
    TaskProofStatusEnum,
)
from app.services.outbox_dispatcher import create_outbox_event, signal_outbox_wake


ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
UPLOAD_BASE_DIR = Path("uploads")
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


def save_task_proof(
    db: Session,
    work_id: int,
    file_content: bytes,
    filename: str,
    employee_id: Optional[int] = None,
    commit: bool = True,
) -> dict:
    """Save a task completion proof image and queue verification.

    Args:
        db:            Active SQLAlchemy session (caller-owned).
        work_id:       ID of the work queue item.
        file_content:  Raw image bytes.
        filename:      Original filename (used for extension validation).
        commit:        Whether to commit the transaction (default True).

    Returns:
        Dict with proof_id, work_id, and proof_image_path.

    Raises:
        HTTPException 404: Work item not found.
        HTTPException 400: Work item not ASSIGNED or bad extension.
        HTTPException 413: File exceeds size limit.
    """
    # Validate work item exists
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
    if employee_id is not None and active_assignment.employee_id != employee_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Employee is not assigned to this work item",
        )
    submitter_id = employee_id or active_assignment.employee_id

    # Validate extension
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"File type '{suffix}' is not allowed. "
                f"Accepted: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            ),
        )

    # Validate size (413 Payload Too Large)
    if len(file_content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum upload size of {MAX_UPLOAD_BYTES // (1024 * 1024)}MB",
        )

    # Create proof record with placeholder path, flush to get proof_id
    attempts = db.query(TaskProof).filter(
        TaskProof.work_id == work_id
    ).count()
    proof_record = TaskProof(
        work_id=work_id,
        employee_id=submitter_id,
        proof_image_path="pending_upload",
        verification_status=TaskProofStatusEnum.PENDING,
        verification_attempts=attempts + 1,
    )
    db.add(proof_record)
    db.flush()

    # Write file to disk
    secure_name = f"{proof_record.proof_id}_{uuid.uuid4().hex[:8]}{suffix}"
    upload_dir = UPLOAD_BASE_DIR / str(work_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / secure_name
    file_path.write_bytes(file_content)

    final_path = f"uploads/{work_id}/{secure_name}"
    proof_record.proof_image_path = final_path

    # Queue outbox event for async verification
    create_outbox_event(
        db,
        event_type="TASK_PROOF_SUBMITTED",
        payload={
            "work_id": work_id,
            "proof_id": proof_record.proof_id,
            "proof_image_path": final_path,
        },
    )

    if commit:
        db.commit()
        signal_outbox_wake()

    return {
        "proof_id": proof_record.proof_id,
        "work_id": work_id,
        "proof_image_path": final_path,
        "employee_id": submitter_id,
        "verification_attempts": attempts + 1,
    }
