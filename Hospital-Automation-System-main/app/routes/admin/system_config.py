"""
Admin System Config Routes

GET  /system-config/  -- returns all config entries sorted by config_key
PUT  /system-config/  -- bulk update with key whitelisting, strict boolean
                         parsing, and min/max operational bounds validation
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.models.system_config import SystemConfig
from app.schemas.system_config import (
    SystemConfigResponse,
    SystemConfigBulkUpdate,
)
from app.services.system_config_service import DEFAULT_CONFIG

router = APIRouter(prefix="/system-config", tags=["Admin - System Config"])


@router.get("/", response_model=list[SystemConfigResponse])
def get_all_config(db: Session = Depends(get_db)):
    """Return all operational config entries sorted by config_key."""
    rows = (
        db.query(SystemConfig)
        .order_by(SystemConfig.config_key.asc())
        .all()
    )
    return rows


@router.put("/", response_model=list[SystemConfigResponse])
def update_config(payload: SystemConfigBulkUpdate, db: Session = Depends(get_db)):
    """Bulk update config values with validation.

    Rejects unknown keys, enforces strict boolean parsing, validates
    numeric types and min/max bounds. Commits all changes in a single
    transaction.
    """
    for item in payload.updates:
        key = item.config_key
        raw_value = item.config_value

        # Reject unknown keys
        if key not in DEFAULT_CONFIG:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid or unauthorized configuration key: {key}",
            )

        meta = DEFAULT_CONFIG[key]
        value_type = meta["value_type"]

        # Type and bounds validation
        if value_type == "boolean":
            if raw_value.strip().lower() not in ("true", "false"):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Invalid boolean value for {key}: '{raw_value}'. "
                        f"Accepted values: 'true' or 'false'."
                    ),
                )

        elif value_type == "integer":
            try:
                parsed = int(raw_value)
            except (ValueError, TypeError):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid integer value for {key}: '{raw_value}'.",
                )
            min_val = meta.get("min_val")
            max_val = meta.get("max_val")
            if min_val is not None and parsed < min_val:
                raise HTTPException(
                    status_code=400,
                    detail=f"{key} must be >= {min_val}, got {parsed}.",
                )
            if max_val is not None and parsed > max_val:
                raise HTTPException(
                    status_code=400,
                    detail=f"{key} must be <= {max_val}, got {parsed}.",
                )

        elif value_type == "float":
            try:
                parsed = float(raw_value)
            except (ValueError, TypeError):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid float value for {key}: '{raw_value}'.",
                )
            min_val = meta.get("min_val")
            max_val = meta.get("max_val")
            if min_val is not None and parsed < min_val:
                raise HTTPException(
                    status_code=400,
                    detail=f"{key} must be >= {min_val}, got {parsed}.",
                )
            if max_val is not None and parsed > max_val:
                raise HTTPException(
                    status_code=400,
                    detail=f"{key} must be <= {max_val}, got {parsed}.",
                )

        # Apply update
        row = db.query(SystemConfig).filter(SystemConfig.config_key == key).first()
        if not row:
            raise HTTPException(status_code=404, detail=f"Config key not found: {key}")
        row.config_value = raw_value

    db.commit()

    # Return updated full config list sorted by key
    rows = (
        db.query(SystemConfig)
        .order_by(SystemConfig.config_key.asc())
        .all()
    )
    return rows
