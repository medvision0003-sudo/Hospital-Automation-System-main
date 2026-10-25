"""
WhatsApp Webhook & Sandbox Routes

Public endpoints:
  GET  /webhook/whatsapp          Meta verification (no auth)
  POST /webhook/whatsapp          Meta webhook payload (signature check)

Protected endpoints:
  POST /webhook/whatsapp/simulate   Admin sandbox (multipart form-data)
  GET  /whatsapp-messages/{eid}     Admin chat history
"""

import os
import hmac
import hashlib
import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.services.whatsapp_service import is_whatsapp_mock_mode
from app.core.dependencies import get_current_user, require_roles
from app.models.enums import UserRoleEnum
from app.models.whatsapp_message import WhatsAppMessage
from app.agents.communication_agent import (
    process_whatsapp_inbound_from_meta_payload,
    send_chat_rules,
)


router = APIRouter(tags=["WhatsApp"])

WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "hospital_verify_token").strip()
WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "").strip()


def _verify_signature(request_body: bytes, signature_header: str) -> bool:
    """Verify Meta webhook signature using HMAC SHA256."""
    if not WHATSAPP_APP_SECRET:
        return False
    expected = "sha256=" + hmac.new(
        WHATSAPP_APP_SECRET.encode(),
        request_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


# Public: Meta webhook verification
@router.get("/webhook/whatsapp")
async def verify_webhook(
    hub_mode: str = None,
    hub_verify_token: str = None,
    hub_challenge: str = None,
):
    """Meta webhook verification handshake.

    Query params use dot notation (hub.mode) which FastAPI
    maps to underscores (hub_mode).
    """
    if hub_mode == "subscribe" and hub_verify_token == WHATSAPP_VERIFY_TOKEN:
        return PlainTextResponse(hub_challenge or "")
    raise HTTPException(status_code=403, detail="Verification failed")


# Public: Meta webhook payload receiver
@router.post("/webhook/whatsapp")
async def receive_webhook(request: Request, db: Session = Depends(get_db)):
    """Process incoming Meta WhatsApp webhook payloads.

    Validates X-Hub-Signature-256 header unless running in mock mode.
    Delegates all Meta payload parsing to the Communication Agent.
    """
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")

    # Diagnostic logging (sanitized for privacy and security)
    try:
        payload = json.loads(body)
        top_keys = list(payload.keys())
        entries = payload.get("entry", [])
        entry_count = len(entries)
        change_count = 0
        message_count = 0
        status_count = 0
        msg_type = "N/A"
        sender_phone = "N/A"
        status_value = "N/A"
        status_recipient = "N/A"
        status_errors = []

        if entries:
            changes = entries[0].get("changes", [])
            change_count = len(changes)
            if changes:
                value = changes[0].get("value", {})
                messages = value.get("messages", [])
                message_count = len(messages)
                if messages:
                    msg_type = messages[0].get("type", "unknown")
                    raw_phone = messages[0].get("from", "")
                    if raw_phone:
                        # Mask phone: keep country code and last 4 digits
                        if len(raw_phone) >= 4:
                            sender_phone = f"{raw_phone[:2]}******{raw_phone[-4:]}"
                        else:
                            sender_phone = raw_phone
                
                statuses = value.get("statuses", [])
                status_count = len(statuses)
                if statuses:
                    status_value = statuses[0].get("status", "unknown")
                    raw_recipient = statuses[0].get("recipient_id", "")
                    if raw_recipient:
                        if len(raw_recipient) >= 4:
                            status_recipient = f"{raw_recipient[:2]}******{raw_recipient[-4:]}"
                        else:
                            status_recipient = raw_recipient
                    status_errors = statuses[0].get("errors", [])

        sig_present = bool(signature)
        sig_preview = signature[:12] if sig_present else ""

        print(
            f"[WHATSAPP_WEBHOOK] Received webhook: "
            f"keys={top_keys} | entries={entry_count} | changes={change_count} | "
            f"messages={message_count} | type={msg_type} | phone={sender_phone} | "
            f"statuses={status_count} | status={status_value} | recipient={status_recipient} | "
            f"errors={status_errors} | "
            f"sig_present={sig_present} | sig_preview={sig_preview}"
        )
    except Exception as e:
        print(f"[WHATSAPP_WEBHOOK] Diagnostic logging error: {e}")
        payload = {}

    # Signature verification (bypassed in mock/sandbox mode)
    if not is_whatsapp_mock_mode():
        if not _verify_signature(body, signature):
            print(f"[WHATSAPP_WEBHOOK] Signature verification failed (sig={signature[:12]})")
            raise HTTPException(status_code=403, detail="Invalid signature")

    if not payload:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    try:
        process_whatsapp_inbound_from_meta_payload(db, payload)
    except Exception as e:
        print(f"[WHATSAPP_WEBHOOK] Error processing payload: {e}")

    return {"status": "ok"}





# Protected: Admin chat history
@router.get(
    "/whatsapp-messages/{employee_id}",
    dependencies=[Depends(require_roles([UserRoleEnum.ADMIN]))],
)
async def get_messages(employee_id: int, db: Session = Depends(get_db)):
    """Retrieve WhatsApp chat history for a given employee."""
    messages = (
        db.query(WhatsAppMessage)
        .filter(WhatsAppMessage.employee_id == employee_id)
        .order_by(WhatsAppMessage.timestamp.asc())
        .all()
    )

    return [
        {
            "message_id": m.message_id,
            "direction": m.direction,
            "body": m.body,
            "media_path": m.media_path,
            "work_id": m.work_id,
            "status": m.status,
            "timestamp": m.timestamp.isoformat() if m.timestamp else None,
        }
        for m in messages
    ]


@router.get("/whatsapp-communication-status")
def get_communication_status(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Expose truthful channel mode and redacted notification history."""
    mock_mode = is_whatsapp_mock_mode()
    messages = (
        db.query(WhatsAppMessage)
        .filter(WhatsAppMessage.direction == "OUTBOUND")
        .order_by(WhatsAppMessage.timestamp.desc())
        .limit(10)
        .all()
    )
    return {
        "delivery_mode": "DEMO" if mock_mode else "LIVE",
        "real_whatsapp_configured": bool(
            os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
            and os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
        ),
        "notifications": [
            {
                "work_id": message.work_id,
                "status": message.status,
                "timestamp": message.timestamp.isoformat() if message.timestamp else None,
            }
            for message in messages
        ],
    }
