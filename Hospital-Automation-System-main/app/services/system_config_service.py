"""
System Config Service

Provides the DEFAULT_CONFIG whitelist, get_config_value() helper,
and seed_system_config() startup routine.

get_config_value performs direct, uncached DB lookups so admin changes
take effect immediately on the next call.
"""

from typing import Any

from sqlalchemy.orm import Session

from app.models.system_config import SystemConfig


# Whitelisted operational config keys with defaults, types, bounds, and descriptions.
# Security settings (JWT, CORS, DB URL, API keys) are intentionally excluded.

DEFAULT_CONFIG = {
    "ENABLE_SOP_LLM_PLANNER": {
        "default_value": "false",
        "value_type": "boolean",
        "description": "Enable SOP-grounded LLM planner for intelligent workflow planning (opt-in).",
        "min_val": None,
        "max_val": None,
    },
    "SHIFT_END_BUFFER_MINUTES": {
        "default_value": "15",
        "value_type": "integer",
        "description": "Minutes before shift end where workers are excluded from new task assignments.",
        "min_val": 0,
        "max_val": 120,
    },
    "SHIFT_GRACE_PERIOD_MINUTES": {
        "default_value": "30",
        "value_type": "integer",
        "description": "Minutes after shift start during which a check-in remains on time.",
        "min_val": 0,
        "max_val": 180,
    },
    "SHIFT_HALF_DAY_THRESHOLD_MINUTES": {
        "default_value": "120",
        "value_type": "integer",
        "description": "Minutes after shift start after which a check-in is classified as HALF_DAY.",
        "min_val": 30,
        "max_val": 360,
    },
    "ABSENTEE_CHECKIN_TIMEOUT_MINUTES": {
        "default_value": "30",
        "value_type": "integer",
        "description": "Minutes after shift start before a worker is marked ABSENT by the watcher.",
        "min_val": 0,
        "max_val": 180,
    },
    "OVERLOAD_ABOVE_AVG_THRESHOLD": {
        "default_value": "3",
        "value_type": "integer",
        "description": "Tasks above the department average before a worker is flagged as overloaded.",
        "min_val": 1,
        "max_val": 20,
    },
    "STAFF_SHORTAGE_MINUTES": {
        "default_value": "20",
        "value_type": "integer",
        "description": "Minutes a task can remain unassigned before triggering STAFF_SHORTAGE_DETECTED.",
        "min_val": 5,
        "max_val": 30,
    },
    "ABSENTEE_SNOOZE_MINUTES": {
        "default_value": "20",
        "value_type": "integer",
        "description": "Minutes to snooze an absentee worker escalation when waiting for them.",
        "min_val": 5,
        "max_val": 60,
    },
    "STUCK_PROCESSING_MINUTES": {
        "default_value": "5",
        "value_type": "integer",
        "description": "Minutes an outbox event can stay in PROCESSING before recovery resets it.",
        "min_val": 1,
        "max_val": 120,
    },
    "HANDOVER_REVIEW_TIMEOUT_MINUTES": {
        "default_value": "15",
        "value_type": "integer",
        "description": "Minutes before a SHIFT_HANDOVER_REVIEW approval is auto-resolved via Choice B.",
        "min_val": 1,
        "max_val": 120,
    },
    "MAX_PHOTO_VERIFICATION_ATTEMPTS": {
        "default_value": "3",
        "value_type": "integer",
        "description": "Maximum proof resubmission attempts before escalating to HUMAN_REVIEW_REQUIRED.",
        "min_val": 1,
        "max_val": 10,
    },
    "MIN_VERIFICATION_CONFIDENCE_SCORE": {
        "default_value": "0.70",
        "value_type": "float",
        "description": "Minimum confidence score from Task Verification Agent to auto-verify a task.",
        "min_val": 0.10,
        "max_val": 1.00,
    },
    "OUTBOX_POLL_INTERVAL_SECONDS": {
        "default_value": "30",
        "value_type": "integer",
        "description": "Seconds between outbox dispatcher polling cycles.",
        "min_val": 5,
        "max_val": 300,
    },
    "OUTBOX_BATCH_LIMIT": {
        "default_value": "20",
        "value_type": "integer",
        "description": "Maximum number of outbox events processed per polling cycle.",
        "min_val": 1,
        "max_val": 100,
    },
    "ENABLE_ORCHESTRATOR_SELF_CORRECTION": {
        "default_value": "false",
        "value_type": "boolean",
        "description": "Enable autonomic recovery and plan self-correction for transient failures.",
        "min_val": None,
        "max_val": None,
    },
    "MAX_REFLECTION_ATTEMPTS": {
        "default_value": "1",
        "value_type": "integer",
        "description": "Maximum number of self-correction attempts allowed per event trace.",
        "min_val": 1,
        "max_val": 5,
    },
    "ENABLE_AUTOMATED_PROOF_APPROVAL": {
        "default_value": "false",
        "value_type": "boolean",
        "description": "Enable high-confidence automated task proof verification and approval (opt-in).",
        "min_val": None,
        "max_val": None,
    },
}


def _cast_value(raw: str, value_type: str) -> Any:
    """Cast a string config_value to its Python type based on value_type."""
    if value_type == "boolean":
        return raw.strip().lower() == "true"
    elif value_type == "integer":
        return int(raw)
    elif value_type == "float":
        return float(raw)
    return raw


def get_config_value(db: Session, key: str, default: Any = None) -> Any:
    """Read a single operational config value from the database.

    Returns fallback on missing key or config query failure.
    On query error, calls db.rollback() to keep the session usable.
    """
    try:
        row = (
            db.query(SystemConfig)
            .filter(SystemConfig.config_key == key)
            .first()
        )
        if row is None:
            return default
        return _cast_value(row.config_value, row.value_type)
    except Exception as exc:
        print(f"[SYSTEM_CONFIG] Query failed for key={key}: {exc}")
        try:
            db.rollback()
        except Exception:
            pass
        return default


def seed_system_config(db: Session) -> None:
    """Idempotently populate missing default config entries on startup.

    Only inserts keys that do not already exist in the table, preserving
    any values previously changed by an administrator.
    """
    existing_keys = {
        row.config_key
        for row in db.query(SystemConfig.config_key).all()
    }

    added = 0
    for key, meta in DEFAULT_CONFIG.items():
        if key not in existing_keys:
            row = SystemConfig(
                config_key=key,
                config_value=meta["default_value"],
                value_type=meta["value_type"],
                description=meta["description"],
            )
            db.add(row)
            added += 1

    if added > 0:
        db.commit()
        print(f"[SYSTEM_CONFIG] Seeded {added} default config entries")
    else:
        print("[SYSTEM_CONFIG] All config entries already present, nothing to seed")
