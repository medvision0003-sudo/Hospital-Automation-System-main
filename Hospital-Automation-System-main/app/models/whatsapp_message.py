"""
WhatsApp Message Model

Logs all inbound and outbound WhatsApp communications for audit,
debugging, and frontend sandbox chat history rendering.
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func
from app.database.base import Base


class WhatsAppMessage(Base):
    __tablename__ = "whatsapp_message"

    message_id = Column(Integer, primary_key=True, autoincrement=True)
    employee_id = Column(
        Integer,
        ForeignKey("employee.employee_id"),
        nullable=True,
    )
    direction = Column(String(10), nullable=False)  # INBOUND or OUTBOUND
    phone_number = Column(String(20), nullable=True)
    body = Column(Text, nullable=True)
    media_path = Column(String(500), nullable=True)
    work_id = Column(
        Integer,
        ForeignKey("department_work_queue.work_id"),
        nullable=True,
    )
    status = Column(String(20), nullable=True)  # SENT, MOCKED, FAILED, RECEIVED
    raw_payload_json = Column(Text, nullable=True)
    timestamp = Column(DateTime, server_default=func.now(), nullable=False)
