from __future__ import annotations

from typing import Optional

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
