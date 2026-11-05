"""A user's home timezone and base currency (#202).

``user_preferences.timezone`` is an IANA name or NULL; NULL (and anything the
API would no longer accept) means the app timezone (``TZ``, default
Asia/Singapore). See ``app.core.clock`` for how a request picks it up.
"""
from __future__ import annotations

from typing import Iterable, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.clock import default_timezone_name, normalize_timezone_name

# The base currencies a page can be shown in (the web app's CURRENCY_OPTIONS).
BASE_CURRENCIES = ("SGD", "USD", "HKD", "INR")

# Where a user's effective timezone comes from (``timezone_source``).
SOURCE_USER = "user"  # chosen by the user (Settings) or filled from their browser
SOURCE_APP = "app"  # an account from before #202: follows the app's TZ
SOURCE_UNSET = "unset"  # not filled yet: the app's TZ until the browser fills it


def stored_timezone(db: Session, user_id: int) -> Optional[str]:
    """The user's valid stored timezone, or None (= the app timezone)."""
    value = db.execute(
        text("SELECT timezone FROM user_preferences WHERE user_id = :user_id"),
        {"user_id": user_id},
    ).scalar()
    return normalize_timezone_name(value)


def effective_timezone(db: Session, user_id: int) -> str:
    return stored_timezone(db, user_id) or default_timezone_name()


def timezones_for_users(db: Session, user_ids: Iterable[int]) -> dict[int, str]:
    """{user_id: effective timezone name} for each of ``user_ids``."""
    return {int(user_id): effective_timezone(db, int(user_id)) for user_id in user_ids}


def timezone_source(timezone_value: Optional[str], timezone_from_app: bool) -> str:
    if normalize_timezone_name(timezone_value):
        return SOURCE_USER
    return SOURCE_APP if timezone_from_app else SOURCE_UNSET
