from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime


class OutboxEventListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: str
    event_type: str
    status: str
    attempts: int
    created_at: datetime
    processed_at: Optional[datetime] = None
    dedupe_key: Optional[str] = None


class OutboxEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: str
    event_type: str
    payload_json: str
    dedupe_key: Optional[str] = None
    status: str
    attempts: int
    last_error: Optional[str] = None
    created_at: datetime
    processed_at: Optional[datetime] = None
    available_after: Optional[datetime] = None
    processing_started_at: Optional[datetime] = None
