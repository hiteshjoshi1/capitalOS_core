"""The Data Hub inbox (#316): one list of what needs the user, each with its action."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from app.schemas.dashboard import DataHubActivityItem


class InboxAction(BaseModel):
    """What the item's button does. Either `route` (a page to open, with `params` as its
    query string) or `run` (a refresh the page runs in place: refresh_prices, fx_backfill,
    refresh_ibkr, refresh_crypto). `admin_only`: the action writes shared data (#152), so
    a non-admin sees the item and who can fix it, without the button."""

    label: str
    route: Optional[str] = None
    params: Dict[str, str] = {}
    run: Optional[str] = None
    admin_only: bool = False


class InboxItem(BaseModel):
    """`kind`: source_overdue, source_never_loaded, unknown_format, import_pending,
    unpriced_holding, fx_gap, fx_unsupported, job_failing, unmapped_transactions,
    card_due_soon, card_overdue (#352), backup_stale (#399), month_closed_stale, concentration,
    unusual_move, recurring_new, recurring_up (#410).
    `severity`: high, medium or low. `source` is the source-freshness row for the
    source kinds (#252), so the page can build the prefilled Upload link (#278)."""

    id: str
    kind: str
    severity: str
    title: str
    detail: Optional[str] = None
    action: Optional[InboxAction] = None
    source: Optional[Dict[str, Any]] = None


class InboxResponse(BaseModel):
    as_of: str
    count: int
    items: List[InboxItem]
    # What's fine, one short line each ("8 sources on time"); collapsed on the page.
    all_good: List[str] = []
    recent_activity: List[DataHubActivityItem] = []
