"""
Protected Uploads Router

Serves uploaded proof files behind authentication.
Replaces the public StaticFiles mount to ensure only
authenticated users can access uploaded task proof images.
"""

from pathlib import Path, PurePosixPath

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse


router = APIRouter(prefix="/uploads", tags=["Protected Uploads"])

UPLOAD_BASE_DIR = Path("uploads")


@router.get("/{file_path:path}")
def get_upload(file_path: str):
    """Serve a file from the uploads directory with path traversal protection."""
    # Reject backslashes
    if "\\" in file_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid upload path",
        )

    # Reject absolute paths
    if file_path.startswith("/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid upload path",
        )

    # Reject traversal components before resolving
    if ".." in PurePosixPath(file_path).parts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid upload path",
        )

    # Resolved-path containment check
    base = UPLOAD_BASE_DIR.resolve()
    target = (base / file_path).resolve()

    if base not in target.parents and target != base:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid upload path",
        )

    if not target.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )

    return FileResponse(str(target))
