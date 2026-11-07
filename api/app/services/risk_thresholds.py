"""The Risk page's concentration thresholds, per user (#253, D-68).

Stored on ``user_preferences`` (migration 080). Each is the percent above which
the Risk page calls a figure concentrated; NULL means the app's default, which
lives in the web app (``web/src/lib/risk.ts``), so the API returns None for it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

# API field -> user_preferences column.
THRESHOLD_COLUMNS = {
    "largest_position_warn_pct": "risk_largest_position_warn_pct",
    "top_n_warn_pct": "risk_top_n_warn_pct",
    "platform_warn_pct": "risk_platform_warn_pct",
}


def _as_float(value: Any) -> Optional[float]:
    return float(value) if value is not None else None


def read_risk_thresholds(db: Session, user_id: int) -> dict[str, Optional[float]]:
    """The user's thresholds; None where they keep the default (or have no row yet)."""
    columns = ", ".join(f"{column} AS {field}" for field, column in THRESHOLD_COLUMNS.items())
    row = db.execute(
        text(f"SELECT {columns} FROM user_preferences WHERE user_id = :user_id"),
        {"user_id": user_id},
    ).mappings().one_or_none()
    return {field: _as_float(row[field]) if row is not None else None for field in THRESHOLD_COLUMNS}


def save_risk_thresholds(db: Session, user_id: int, values: Mapping[str, Optional[float]]) -> dict[str, Optional[float]]:
    """Replace the user's thresholds (None: back to the default). Creates the
    preferences row with its defaults when the user has none yet. Commits."""
    params: dict[str, Any] = {field: values.get(field) for field in THRESHOLD_COLUMNS}
    columns = ", ".join(THRESHOLD_COLUMNS.values())
    placeholders = ", ".join(f":{field}" for field in THRESHOLD_COLUMNS)
    updates = ", ".join(f"{column} = excluded.{column}" for column in THRESHOLD_COLUMNS.values())
    db.execute(
        text(
            f"""
            INSERT INTO user_preferences (user_id, {columns}, updated_at)
            VALUES (:user_id, {placeholders}, :now)
            ON CONFLICT (user_id) DO UPDATE SET {updates}, updated_at = excluded.updated_at
            """
        ),
        {**params, "user_id": user_id, "now": datetime.now(tz=timezone.utc)},
    )
    db.commit()
    return read_risk_thresholds(db, user_id)
