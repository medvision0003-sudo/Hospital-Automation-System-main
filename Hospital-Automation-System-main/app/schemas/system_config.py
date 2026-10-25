"""
Pydantic schemas for the SystemConfig API.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class SystemConfigResponse(BaseModel):
    """Serializes a single system_config row for GET responses."""
    config_key: str
    config_value: str
    value_type: str
    description: Optional[str] = None
    last_updated: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class SystemConfigItemUpdate(BaseModel):
    """A single config key/value update payload."""
    config_key: str
    config_value: str


class SystemConfigBulkUpdate(BaseModel):
    """Accepts a list of config updates for bulk PUT."""
    updates: list[SystemConfigItemUpdate]
