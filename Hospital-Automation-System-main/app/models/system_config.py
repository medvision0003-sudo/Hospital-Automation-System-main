"""
SystemConfig Model

Stores runtime-configurable operational settings (grace periods, buffer
times, feature flags, watcher thresholds) in a relational table.

Security credentials (JWT secrets, CORS origins, DB URL, API keys) are
excluded from this table and remain in .env only.
"""

from sqlalchemy import Column, String, DateTime, func

from app.database.base import Base


class SystemConfig(Base):
    __tablename__ = "system_config"

    config_key = Column(String(100), primary_key=True, index=True)
    config_value = Column(String(255), nullable=False)
    value_type = Column(String(50), nullable=False)
    description = Column(String(255), nullable=True)
    last_updated = Column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
