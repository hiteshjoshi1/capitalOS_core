from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class UploadReminderAlert(BaseModel):
    account_id: int
    account_name: str
    platform: str
    account_type: str
    last_upload_date: Optional[str]
    last_transaction_date: Optional[str]
    days_since_upload: int
    message: str


class UploadReminderCountResponse(BaseModel):
    count: int


class SystemNotification(BaseModel):
    id: str
    alert_type: str = "system_notification"
    topic: str
    event_name: str
    author_id: Optional[str] = None
    source_id: Optional[str] = None
    job_id: Optional[str] = None
    batch_id: Optional[str] = None
    status: Optional[str] = None
    message: str
    created_at: str
    payload: Dict[str, Any] = {}


class UnifiedAlertsResponse(BaseModel):
    upload_reminders: List[UploadReminderAlert]
    system_notifications: List[SystemNotification]
    total_count: int
