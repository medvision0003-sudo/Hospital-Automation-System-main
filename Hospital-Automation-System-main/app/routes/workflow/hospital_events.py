"""
Hospital Events Gateway -- Single entry point for all hospital events.

This route knows NOTHING about specific event types, payloads,
or validation rules.  It receives an event envelope.

For sync=True requests, it validates and processes immediately via the Event Agent.
For sync=False (default), it writes to the transactional outbox for
background processing by the outbox dispatcher daemon.

For EMERGENCY_RESPONSE events the gateway translates legacy
emergency type strings (e.g. "CODE_BLUE") into clean
EmergencyTypeEnum values before forwarding the payload.

Flow:
    POST /events  ->  Event Gateway  ->  outbox_event record  ->  OutboxDispatcher
                                              |
                                         Event Agent  (validation)
                                              |
                                         Orchestrator (workflow)
"""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.models.enums import HospitalEventEnum, EmergencyTypeEnum
from app.agents.event_agent import publish_event
from app.services.outbox_dispatcher import create_outbox_event, signal_outbox_wake
from app.utils.emergency_mapping import translate_emergency_type

router = APIRouter(prefix="/events", tags=["Workflow - Event Gateway"])


class EventRequest(BaseModel):
    event_type: HospitalEventEnum
    payload: dict


def _translate_emergency_payload(payload: dict) -> dict:
    """Return a copy of the payload with a translated emergency_type.

    Raises HTTPException(400) if the translated value is not a
    valid EmergencyTypeEnum member.
    """
    translated = dict(payload)
    raw_type = translated.get("emergency_type")
    if raw_type is None:
        return translated

    clean_type = translate_emergency_type(str(raw_type))
    try:
        EmergencyTypeEnum(clean_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown emergency type: '{raw_type}'",
        )
    translated["emergency_type"] = clean_type
    return translated


@router.post("/")
def submit_event(
    body: EventRequest,
    response: Response,
    sync: bool = False,
    db: Session = Depends(get_db),
):
    """
    Submit a hospital event for processing.
    """
    if body.event_type in {
        HospitalEventEnum.WORKER_CHECKED_IN,
        HospitalEventEnum.WORKER_CHECKED_OUT,
    } and body.payload.get("trigger_source") != "MANUAL_OVERRIDE":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Attendance events submitted through this endpoint must be "
                "explicitly marked as a demo/manual override. Production "
                "attendance must use the registered device API."
            ),
        )

    # Translate legacy emergency types before any downstream processing
    effective_payload = body.payload
    if body.event_type == HospitalEventEnum.EMERGENCY_RESPONSE:
        effective_payload = _translate_emergency_payload(body.payload)

    if sync:
        try:
            result = publish_event(body.event_type, effective_payload, db)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        workflow_status = result.get("status")
        if getattr(workflow_status, "value", workflow_status) == "FAILED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=result.get("reason", "Event workflow could not be completed"),
            )
        response.status_code = status.HTTP_200_OK
        return result

    # Async: write to outbox and commit
    create_outbox_event(db, body.event_type.value, effective_payload)
    db.commit()
    signal_outbox_wake()

    response.status_code = status.HTTP_202_ACCEPTED
    return {
        "status": "Accepted",
        "event_type": body.event_type.value,
        "message": "Event queued for processing via outbox",
    }
