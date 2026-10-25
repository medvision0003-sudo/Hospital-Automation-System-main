from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.database.connection import get_db
from app.models.event_log import EventLog
from app.schemas.event_log import EventLogResponse

router = APIRouter(prefix="/event-logs", tags=["Query - Event Logs"])


@router.get("/", response_model=List[EventLogResponse])
def get_all_events(db: Session = Depends(get_db)):
    events = db.query(EventLog).all()
    return events


@router.get("/type/{event_type}", response_model=List[EventLogResponse])
def get_events_by_type(event_type: str, db: Session = Depends(get_db)):
    normalized_type = event_type.strip().upper()
    events = db.query(EventLog).filter(
        EventLog.event_log == normalized_type
    ).all()

    return events


@router.get("/{event_id}", response_model=EventLogResponse)
def get_event(event_id: int, db: Session = Depends(get_db)):
    event = db.query(EventLog).filter(
        EventLog.event_id == event_id
    ).first()

    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    return event
