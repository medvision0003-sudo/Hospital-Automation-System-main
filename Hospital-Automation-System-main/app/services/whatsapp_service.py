"""
WhatsApp Service (Channel Helper)

Low-level WhatsApp channel delivery and message persistence.
Handles:
  Meta Cloud API calls (send text, download media)
  WhatsAppMessage row persistence (inbound/outbound)
  Phone number normalization
  Employee phone lookup
  Active task queries

This module contains NO business logic, NO AgentActionLog writes,
and NO EventLog writes. Those belong in communication_agent.py.
"""

import os
import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.department_work_queue import DepartmentWorkQueue
from app.models.task_assignment import TaskAssignment
from app.models.task_master import TaskMaster
from app.models.whatsapp_message import WhatsAppMessage
from app.models.enums import AssignmentStatusEnum

WHATSAPP_MOCK = (
    os.getenv("WHATSAPP_MOCK", os.getenv("DEMO_MODE", "true"))
    .lower()
    .strip()
    == "true"
)
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()


def is_whatsapp_mock_mode() -> bool:
    """Keep delivery mocked unless live mode and both credentials are configured."""
    return WHATSAPP_MOCK or not (
        WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID
    )


def _send_outbound_api_call(phone: str, body: str) -> str:
    """Send an outbound text message to WhatsApp Cloud API."""
    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        print("[COMMUNICATION_AGENT] Missing token or phone ID. Check your environment variables.")
        return "FAILED"

    # Normalize phone: ensure only digits, with country code (defaults to 91 for India)
    clean_phone = "".join(c for c in phone if c.isdigit())
    if len(clean_phone) == 10:
        clean_phone = "91" + clean_phone

    url = f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": clean_phone,
        "type": "text",
        "text": {
            "body": body
        }
    }

    try:
        import requests
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        if response.status_code in (200, 201):
            return "SENT"
        print(f"[COMMUNICATION_AGENT] WhatsApp send failed ({response.status_code}): {response.text}")
        return "FAILED"
    except Exception as e:
        print(f"[COMMUNICATION_AGENT] Request exception: {e}")
        return "FAILED"


def download_meta_media(media_id: str) -> tuple[bytes, str]:
    """Retrieve media details from Meta, then download the binary content."""
    if not WHATSAPP_ACCESS_TOKEN or not media_id:
        return None, None

    headers = {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"}
    try:
        import requests
        # Step 1: Get media URL
        url = f"https://graph.facebook.com/v20.0/{media_id}"
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            print(f"[COMMUNICATION_AGENT] Failed to get media URL: {res.text}")
            return None, None

        media_url = res.json().get("url")
        if not media_url:
            return None, None

        # Step 2: Download binary content
        bin_res = requests.get(media_url, headers=headers, timeout=15)
        if bin_res.status_code == 200:
            content_type = bin_res.headers.get("content-type", "")
            ext = ".jpg"
            if "png" in content_type:
                ext = ".png"
            elif "webp" in content_type:
                ext = ".webp"
            elif "gif" in content_type:
                ext = ".gif"
            return bin_res.content, ext
    except Exception as e:
        print(f"[COMMUNICATION_AGENT] Media download exception: {e}")
    return None, None


def normalize_phone(phone: str) -> str:
    """Extract last 10 digits from a phone number for prototype matching."""
    digits = "".join(c for c in phone if c.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


def find_employee_by_phone(db: Session, phone: str):
    """Look up employee by last-10-digit phone match."""
    normalized = normalize_phone(phone)
    if not normalized:
        return None
    employees = db.query(Employee).all()
    for emp in employees:
        if emp.phone and normalize_phone(emp.phone) == normalized:
            return emp
    return None


def deliver_whatsapp_message(db: Session, employee_id, phone, body, work_id=None) -> WhatsAppMessage:
    """Send (or mock) an outbound WhatsApp message and persist it.

    This is the single outbound delivery entry point. It:
      1. Prepends a date header if first message today for this recipient.
      2. Calls the Meta Graph API (or logs a mock).
      3. Writes a WhatsAppMessage row.
    """
    # Prepend date header if first message today for this recipient
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    exists_today = False

    clean_phone = normalize_phone(phone) if phone else None
    query = db.query(WhatsAppMessage).filter(WhatsAppMessage.timestamp >= today_start)
    if employee_id:
        query = query.filter(WhatsAppMessage.employee_id == employee_id)
        exists_today = query.first() is not None
    elif clean_phone:
        all_today = query.all()
        for m in all_today:
            if m.phone_number and normalize_phone(m.phone_number) == clean_phone:
                exists_today = True
                break

    if not exists_today:
        date_header = f"=== {datetime.now().strftime('%Y-%m-%d')} ===\n\n"
        body = date_header + body

    # Send via API or mock
    if is_whatsapp_mock_mode():
        sent_status = "MOCKED"
    else:
        sent_status = _send_outbound_api_call(phone, body) if phone else "FAILED"

    msg = WhatsAppMessage(
        employee_id=employee_id,
        direction="OUTBOUND",
        phone_number=phone,
        body=body,
        work_id=work_id,
        status=sent_status,
    )
    db.add(msg)
    db.flush()
    return msg


def log_inbound(db: Session, employee_id, phone, body, work_id=None, media_path=None,
                raw_payload=None) -> WhatsAppMessage:
    """Write an INBOUND WhatsAppMessage row (does not commit)."""
    msg = WhatsAppMessage(
        employee_id=employee_id,
        direction="INBOUND",
        phone_number=phone,
        body=body,
        work_id=work_id,
        media_path=media_path,
        status="RECEIVED",
        raw_payload_json=json.dumps(raw_payload, default=str) if raw_payload else None,
    )
    db.add(msg)
    db.flush()
    return msg


def get_active_tasks(db: Session, employee_id: int) -> list[dict]:
    """Get the employee's active task assignments with work item details."""
    assignments = (
        db.query(TaskAssignment)
        .filter(
            TaskAssignment.employee_id == employee_id,
            TaskAssignment.assignment_status.in_([
                AssignmentStatusEnum.ASSIGNED,
                AssignmentStatusEnum.IN_PROGRESS,
            ]),
        )
        .all()
    )

    tasks = []
    for a in assignments:
        work_item = db.query(DepartmentWorkQueue).filter(
            DepartmentWorkQueue.work_id == a.work_id
        ).first()
        if not work_item:
            continue
        task = db.query(TaskMaster).filter(TaskMaster.task_id == work_item.task_id).first()
        task_name = task.task_name if task else f"Task #{work_item.task_id}"
        due_str = work_item.due_date.strftime("%H:%M") if work_item.due_date else "N/A"
        priority = work_item.priority.value if work_item.priority else "MEDIUM"

        tasks.append({
            "index": len(tasks) + 1,
            "work_id": a.work_id,
            "assignment_id": a.assignment_id,
            "task_name": task_name,
            "priority": priority,
            "due": due_str,
            "status": a.assignment_status.value,
        })

    return tasks
