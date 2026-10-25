
from sqlalchemy import Column, Integer, String, DateTime, Text, func
from sqlalchemy.orm import relationship
from app.database.base import Base


class AgentTable(Base):
    __tablename__ = "agent_table"

    agent_id = Column(Integer, primary_key=True)

    agent_name = Column(String(100), unique=True, nullable=False)

    agent_category = Column(String(100), nullable=False)

    description = Column(Text)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    actions = relationship(
        "AgentActionLog",
        back_populates="agent",
    )
