"""Settings → How CapitalOS counts (#399, U24): GET /settings/facts, read-only server settings."""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends

from app.auth_context import require_current_user
from app.schemas.operations import SettingsFactsOut
from app.services.user_preferences import BASE_CURRENCIES
from app.valuation.clock import _configured_snapshot_day

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(require_current_user)])


def upload_stale_days() -> int:
    # Same reading as the upload reminders (routers/alerts.py).
    try:
        return int(os.environ.get("UPLOAD_STALE_DAYS", "30"))
    except (ValueError, TypeError):
        return 30


@router.get("/facts", response_model=SettingsFactsOut)
def settings_facts():
    """The month's snapshot day, the default upload cadence and the base currencies. Server
    configuration, the same for every user."""
    return SettingsFactsOut(
        snapshot_day=_configured_snapshot_day(),
        upload_stale_days=upload_stale_days(),
        base_currencies=list(BASE_CURRENCIES),
    )
