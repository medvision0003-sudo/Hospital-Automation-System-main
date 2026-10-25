"""
SOP Retriever Service

Scans the local knowledge_base/sops/ directory for Markdown files
with YAML frontmatter metadata, and matches incoming event triggers
to the appropriate Standard Operating Procedure document.

For DYNAMIC_TASK_REQUEST events the payload only carries task_id,
so the retriever accepts a DB session to resolve task_id -> task_name
before attempting file matching.
"""

import os
import re
from pathlib import Path
from typing import Optional, Tuple

from sqlalchemy.orm import Session


# Simple regex frontmatter parser, no pyyaml dependency needed
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_FIELD_RE = re.compile(r"^(\w+):\s*(.+)$", re.MULTILINE)

# Resolve base path relative to project root
_SOP_DIR = Path(__file__).resolve().parent.parent.parent / "knowledge_base" / "sops"


def _parse_frontmatter(text: str) -> dict:
    """Extract frontmatter key-value pairs from a Markdown string."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}
    block = match.group(1)
    return {m.group(1): m.group(2).strip() for m in _FIELD_RE.finditer(block)}


def _load_all_sops() -> list[Tuple[dict, str, str]]:
    """Load all SOP files and return (metadata, body_text, filename) tuples."""
    if not _SOP_DIR.is_dir():
        return []

    results = []
    for filepath in sorted(_SOP_DIR.glob("*.md")):
        text = filepath.read_text(encoding="utf-8")
        meta = _parse_frontmatter(text)
        if meta:
            # Body is everything after the closing ---
            body_match = _FRONTMATTER_RE.match(text)
            body = text[body_match.end():].strip() if body_match else text
            results.append((meta, body, filepath.name))
    return results


def _resolve_task_name(task_id: int, db: Session) -> Optional[str]:
    """Resolve a task_id to its task_name via the TaskMaster model."""
    from app.models.task_master import TaskMaster
    task = db.query(TaskMaster).filter(TaskMaster.task_id == task_id).first()
    if task:
        return task.task_name
    return None


def retrieve_sop(
    event_type: str,
    payload: dict,
    db: Optional[Session] = None,
) -> Tuple[Optional[str], Optional[dict]]:
    """Find the best matching SOP for an event trigger.

    Args:
        event_type:  HospitalEventEnum value string (e.g. "EMERGENCY_RESPONSE").
        payload:     Event payload dict.
        db:          Optional SQLAlchemy session for resolving task_id -> task_name.

    Returns:
        (sop_body_text, metadata_dict) if a match is found, else (None, None).
    """
    sops = _load_all_sops()
    if not sops:
        return None, None

    for meta, body, filename in sops:
        if meta.get("event_trigger") != event_type:
            continue

        # Emergency events: match on emergency_type sub-field
        if event_type == "EMERGENCY_RESPONSE":
            sop_etype = meta.get("emergency_type")
            payload_etype = payload.get("emergency_type")
            if sop_etype and payload_etype and sop_etype == payload_etype:
                meta["_filename"] = filename
                return body, meta

        # Task request events: match on task_name (resolved from task_id via DB)
        elif event_type == "DYNAMIC_TASK_REQUEST":
            sop_task_name = meta.get("task_name")
            if sop_task_name and db is not None:
                task_id = payload.get("task_id")
                if task_id is not None:
                    resolved_name = _resolve_task_name(task_id, db)
                    if resolved_name and resolved_name.upper() == sop_task_name.upper():
                        meta["_filename"] = filename
                        return body, meta

        # Generic fallback: match on event_trigger alone (no sub-field)
        else:
            meta["_filename"] = filename
            return body, meta

    return None, None
