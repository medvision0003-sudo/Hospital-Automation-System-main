from sqlalchemy import Column, String, DateTime, Text, Integer, func
from app.database.base import Base


class OutboxEvent(Base):
    __tablename__ = "outbox_event"

    event_id = Column(String(36), primary_key=True, index=True)
    event_type = Column(String(50), nullable=False)
    payload_json = Column(Text, nullable=False)
    dedupe_key = Column(String(255), unique=True, nullable=True)
    status = Column(String(20), default="PENDING", nullable=False)
    attempts = Column(Integer, default=0, nullable=False)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    processed_at = Column(DateTime, nullable=True)
    available_after = Column(DateTime, nullable=True)
    processing_started_at = Column(DateTime, nullable=True)
