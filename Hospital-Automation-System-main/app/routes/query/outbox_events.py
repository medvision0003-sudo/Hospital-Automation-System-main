from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional

from app.database.connection import get_db
from app.models.outbox_event import OutboxEvent
from app.schemas.outbox_event import OutboxEventListItem, OutboxEventResponse

router = APIRouter(
    prefix="/outbox-events",
    tags=["Query - Outbox Events"],
)


@router.get("/", response_model=List[OutboxEventListItem])
def list_outbox_events(
    limit: int = 50,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(OutboxEvent)

    if status:
        query = query.filter(OutboxEvent.status == status)

    return (
        query.order_by(OutboxEvent.created_at.desc())
        .limit(limit)
        .all()
    )


@router.get("/{event_id}", response_model=OutboxEventResponse)
def get_outbox_event(event_id: str, db: Session = Depends(get_db)):
    event = (
        db.query(OutboxEvent)
        .filter(OutboxEvent.event_id == event_id)
        .first()
    )
    if not event:
        raise HTTPException(status_code=404, detail="Outbox event not found")
    return event
