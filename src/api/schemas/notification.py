"""Pydantic schemas for Notification endpoints."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class NotificationCreate(BaseModel):
    """Schema for creating a notification (internal use)."""
    client_id: int
    title: str
    body: str
    type: str = "info"


class NotificationResponse(BaseModel):
    """Schema for notification API response."""
    id: int
    client_id: int
    title: str
    body: str
    type: str
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True


class NotificationListResponse(BaseModel):
    """Schema for paginated notification list."""
    items: list[NotificationResponse]
    total: int
    page: int
    size: int


class UnreadCountResponse(BaseModel):
    """Schema for unread notification count."""
    count: int
