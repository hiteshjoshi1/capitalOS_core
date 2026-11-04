"""Source authority: which source's canonical facts count, and from when (#140).

One mechanism, two layers:

- **Rows carry the answer.** Readers decide whether a position, cash or NAV
  snapshot counts from its ``authority_status`` alone (``authoritative_sql``).
  Nothing else (in particular, no window lookup) makes a row count.
- **Windows decide it at write time.** ``portfolio_source_authority_windows``
  holds exactly one row per (broker account, source, scope). An importer looks
  its window up and stamps each fact ``authoritative`` when the window covers
  the fact's date, else ``reference``. Readers also use the window to route a
  legacy account to the broker account that owns it on a date
  (``window_covers_sql``), never to promote a row.

Windows never move as a side effect of an import: an import creates the window
when there is none and otherwise leaves it alone (a statement that starts
earlier is stored as reference before the window). Moving or closing a window
is an explicit call to ``move_window`` (``make authority-window-move``), which
logs the change in ``portfolio_source_authority_window_changes``, restamps the
source's facts on that broker account, and marks History dirty from the
earliest affected date (D-29).

Overlaps are refused: one row per (broker account, source, scope) is a unique
index, and two sources on the same broker account may not hold overlapping
authoritative windows for overlapping scopes (``all`` overlaps every scope),
checked here on every create and move.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.wealth_rollup_dirty import mark_rollups_dirty

logger = logging.getLogger(__name__)

AUTHORITATIVE = "authoritative"
REFERENCE = "reference"
SUPERSEDED = "superseded"

FLEX_SOURCE_KIND = "ibkr_flex_daily"
FLEX_FACT_SCOPE = "all"
ALL_SCOPES = "all"

# Tables whose rows a Flex window stamps (and a Flex window move restamps).
FLEX_FACT_TABLES = (
    "portfolio_position_snapshots",
    "portfolio_cash_balance_snapshots",
    "portfolio_nav_snapshots",
)


class AuthorityWindowError(Exception):
    """A window change that was refused (overlap, bad dates, missing window)."""


def authoritative_sql(alias: str) -> str:
    """The one reader predicate: does this canonical fact row count?"""
    return f"{alias}.authority_status = '{AUTHORITATIVE}'"


def window_covers_sql(window_alias: str, date_expr: str) -> str:
    """Is the window an authoritative one covering ``date_expr``? (routing only)"""
    w = window_alias
    return (
        f"{w}.authority_status = '{AUTHORITATIVE}' "
        f"AND {w}.effective_from <= {date_expr} "
        f"AND ({w}.effective_to IS NULL OR {w}.effective_to >= {date_expr})"
    )


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _now() -> datetime:
    return datetime.now(tz=timezone.utc).replace(microsecond=0)


@dataclass(frozen=True)
class AuthorityWindow:
    id: int
    broker_account_id: int
    source_kind: str
    fact_scope: str
    effective_from: date
    effective_to: date | None
    authority_status: str

    def covers(self, on_date: date) -> bool:
        return (
            self.authority_status == AUTHORITATIVE
            and self.effective_from <= on_date
            and (self.effective_to is None or self.effective_to >= on_date)
        )

    def status_for(self, on_date: date) -> str:
        return AUTHORITATIVE if self.covers(on_date) else REFERENCE


_WINDOW_COLUMNS = "id, broker_account_id, source_kind, fact_scope, effective_from, effective_to, authority_status"


def _window_from_row(row: Any) -> AuthorityWindow:
    return AuthorityWindow(
        id=int(row[0]),
        broker_account_id=int(row[1]),
        source_kind=str(row[2]),
        fact_scope=str(row[3]),
        effective_from=_as_date(row[4]),  # type: ignore[arg-type]
        effective_to=_as_date(row[5]),
        authority_status=str(row[6]),
    )


def get_window(db: Session, broker_account_id: int, source_kind: str, fact_scope: str) -> AuthorityWindow | None:
    row = db.execute(
        text(
            f"""
            SELECT {_WINDOW_COLUMNS}
            FROM portfolio_source_authority_windows
            WHERE broker_account_id = :broker_account_id
              AND source_kind = :source_kind
              AND fact_scope = :fact_scope
            """
        ),
        {"broker_account_id": broker_account_id, "source_kind": source_kind, "fact_scope": fact_scope},
    ).fetchone()
    return _window_from_row(row) if row is not None else None


def list_windows(db: Session, broker_account_id: int | None = None) -> list[AuthorityWindow]:
    rows = db.execute(
        text(
            f"""
            SELECT {_WINDOW_COLUMNS}
            FROM portfolio_source_authority_windows
            WHERE (:broker_account_id IS NULL OR broker_account_id = :broker_account_id)
            ORDER BY broker_account_id, source_kind, fact_scope
            """
        ),
        {"broker_account_id": broker_account_id},
    ).fetchall()
    return [_window_from_row(row) for row in rows]


def _check_dates(effective_from: date, effective_to: date | None) -> None:
    if effective_to is not None and effective_to < effective_from:
        raise AuthorityWindowError(
            f"effective_to {effective_to.isoformat()} is before effective_from {effective_from.isoformat()}"
        )


def _check_no_overlap(
    db: Session,
    *,
    broker_account_id: int,
    source_kind: str,
    fact_scope: str,
    effective_from: date,
    effective_to: date | None,
) -> None:
    """Refuse when another source holds an overlapping authoritative window here."""
    rows = db.execute(
        text(
            f"""
            SELECT {_WINDOW_COLUMNS}
            FROM portfolio_source_authority_windows
            WHERE broker_account_id = :broker_account_id
              AND source_kind <> :source_kind
              AND authority_status = '{AUTHORITATIVE}'
              AND (fact_scope = :fact_scope OR fact_scope = '{ALL_SCOPES}' OR :fact_scope = '{ALL_SCOPES}')
            """
        ),
        {"broker_account_id": broker_account_id, "source_kind": source_kind, "fact_scope": fact_scope},
    ).fetchall()
    for row in rows:
        other = _window_from_row(row)
        starts_before_other_ends = other.effective_to is None or effective_from <= other.effective_to
        other_starts_before_end = effective_to is None or other.effective_from <= effective_to
        if starts_before_other_ends and other_starts_before_end:
            raise AuthorityWindowError(
                f"overlaps window {other.id} ({other.source_kind}/{other.fact_scope} from "
                f"{other.effective_from.isoformat()}) on broker account {broker_account_id}"
            )


def _log_change(
    db: Session,
    *,
    window_id: int | None,
    broker_account_id: int,
    source_kind: str,
    fact_scope: str,
    action: str,
    old: AuthorityWindow | None,
    new_from: date | None,
    new_to: date | None,
    new_status: str | None,
    reason: str,
    actor: str,
) -> None:
    db.execute(
        text(
            """
            INSERT INTO portfolio_source_authority_window_changes
              (window_id, broker_account_id, source_kind, fact_scope, action,
               old_effective_from, old_effective_to, old_authority_status,
               new_effective_from, new_effective_to, new_authority_status,
               reason, actor, changed_at)
            VALUES
              (:window_id, :broker_account_id, :source_kind, :fact_scope, :action,
               :old_from, :old_to, :old_status,
               :new_from, :new_to, :new_status,
               :reason, :actor, :changed_at)
            """
        ),
        {
            "window_id": window_id,
            "broker_account_id": broker_account_id,
            "source_kind": source_kind,
            "fact_scope": fact_scope,
            "action": action,
            "old_from": old.effective_from if old else None,
            "old_to": old.effective_to if old else None,
            "old_status": old.authority_status if old else None,
            "new_from": new_from,
            "new_to": new_to,
            "new_status": new_status,
            "reason": reason[:500],
            "actor": actor[:200],
            "changed_at": _now(),
        },
    )
    logger.info(
        "authority_window_changed",
        extra={
            "event": "authority_window_changed",
            "action": action,
            "window_id": window_id,
            "broker_account_id": broker_account_id,
            "source_kind": source_kind,
            "fact_scope": fact_scope,
            "old_effective_from": old.effective_from.isoformat() if old else None,
            "new_effective_from": new_from.isoformat() if new_from else None,
            "new_effective_to": new_to.isoformat() if new_to else None,
            "reason": reason,
            "actor": actor,
        },
    )


def ensure_window(
    db: Session,
    *,
    broker_account_id: int,
    source_kind: str,
    fact_scope: str,
    effective_from: date,
    reason: str,
    actor: str = "import",
    effective_to: date | None = None,
) -> tuple[AuthorityWindow, bool]:
    """The source's window on this broker account, created at ``effective_from``
    if there is none. An existing window is returned unchanged whatever date is
    asked for: only ``move_window`` moves one. Returns (window, created)."""
    existing = get_window(db, broker_account_id, source_kind, fact_scope)
    if existing is not None:
        return existing, False
    _check_dates(effective_from, effective_to)
    _check_no_overlap(
        db,
        broker_account_id=broker_account_id,
        source_kind=source_kind,
        fact_scope=fact_scope,
        effective_from=effective_from,
        effective_to=effective_to,
    )
    db.execute(
        text(
            f"""
            INSERT INTO portfolio_source_authority_windows
              (broker_account_id, source_kind, fact_scope, effective_from, effective_to, authority_status)
            VALUES
              (:broker_account_id, :source_kind, :fact_scope, :effective_from, :effective_to, '{AUTHORITATIVE}')
            ON CONFLICT (broker_account_id, source_kind, fact_scope) DO NOTHING
            """
        ),
        {
            "broker_account_id": broker_account_id,
            "source_kind": source_kind,
            "fact_scope": fact_scope,
            "effective_from": effective_from,
            "effective_to": effective_to,
        },
    )
    window = get_window(db, broker_account_id, source_kind, fact_scope)
    assert window is not None
    if window.effective_from != effective_from or window.effective_to != effective_to:
        # A concurrent import created it first: theirs stands.
        return window, False
    _log_change(
        db,
        window_id=window.id,
        broker_account_id=broker_account_id,
        source_kind=source_kind,
        fact_scope=fact_scope,
        action="created",
        old=None,
        new_from=window.effective_from,
        new_to=window.effective_to,
        new_status=window.authority_status,
        reason=reason,
        actor=actor,
    )
    return window, True


def close_windows_superseded_by(db: Session, window: AuthorityWindow, *, reason: str, actor: str = "import") -> int:
    """Close other sources' open windows on the same legacy account and platform
    (e.g. the IBKR CSV upload window once IBKR Flex takes over). They end the day
    before ``window`` starts; one that starts on or after it is marked superseded.
    Returns how many were closed."""
    rows = db.execute(
        text(
            f"""
            SELECT aw.id, aw.broker_account_id, aw.source_kind, aw.fact_scope,
                   aw.effective_from, aw.effective_to, aw.authority_status
            FROM portfolio_source_authority_windows aw
            JOIN broker_accounts ba ON ba.id = aw.broker_account_id
            JOIN broker_connections bc ON bc.id = ba.connection_id
            JOIN broker_accounts owner_ba ON owner_ba.id = :broker_account_id
            JOIN broker_connections owner_bc ON owner_bc.id = owner_ba.connection_id
            WHERE ba.legacy_account_id = owner_ba.legacy_account_id
              AND ba.id <> owner_ba.id
              AND bc.platform_code = owner_bc.platform_code
              AND aw.source_kind <> :source_kind
              AND aw.authority_status = '{AUTHORITATIVE}'
              AND (aw.effective_to IS NULL OR aw.effective_to >= :effective_from)
            ORDER BY aw.id
            """
        ),
        {
            "broker_account_id": window.broker_account_id,
            "source_kind": window.source_kind,
            "effective_from": window.effective_from,
        },
    ).fetchall()
    closed = 0
    for row in rows:
        other = _window_from_row(row)
        day_before = window.effective_from - timedelta(days=1)
        new_to: date | None
        if other.effective_from <= day_before:
            new_to, new_status = day_before, AUTHORITATIVE
        else:
            new_to, new_status = other.effective_to, SUPERSEDED
        db.execute(
            text(
                """
                UPDATE portfolio_source_authority_windows
                SET effective_to = :effective_to, authority_status = :authority_status
                WHERE id = :id
                """
            ),
            {"id": other.id, "effective_to": new_to, "authority_status": new_status},
        )
        _log_change(
            db,
            window_id=other.id,
            broker_account_id=other.broker_account_id,
            source_kind=other.source_kind,
            fact_scope=other.fact_scope,
            action="closed",
            old=other,
            new_from=other.effective_from,
            new_to=new_to,
            new_status=new_status,
            reason=f"{reason}: superseded by window {window.id} ({window.source_kind})",
            actor=actor,
        )
        closed += 1
    return closed


@dataclass(frozen=True)
class WindowMove:
    before: AuthorityWindow | None
    after: AuthorityWindow
    rows_promoted: dict[str, int]
    rows_demoted: dict[str, int]
    applied: bool


def _restamp_counts(db: Session, window: AuthorityWindow, *, count_only: bool) -> tuple[dict[str, int], dict[str, int]]:
    """Make the Flex facts on the window's broker account match the window.

    Only rows written by that source's import runs, and only between
    authoritative and reference (superseded rows stay as they are)."""
    promoted: dict[str, int] = {}
    demoted: dict[str, int] = {}
    params = {
        "broker_account_id": window.broker_account_id,
        "source_kind": window.source_kind,
        "effective_from": window.effective_from,
        "effective_to": window.effective_to,
        "window_status": window.authority_status,
        "now": _now(),
    }
    covered = (
        f"(:window_status = '{AUTHORITATIVE}' AND report_date >= :effective_from "
        "AND (:effective_to IS NULL OR report_date <= :effective_to))"
    )
    own_rows = (
        "broker_account_id = :broker_account_id "
        "AND import_run_id IN (SELECT id FROM broker_import_runs WHERE source_type = :source_kind)"
    )
    for table in FLEX_FACT_TABLES:
        demote_where = f"{own_rows} AND authority_status = '{AUTHORITATIVE}' AND NOT {covered}"
        promote_where = f"{own_rows} AND authority_status = '{REFERENCE}' AND {covered}"
        if count_only:
            demoted[table] = int(db.execute(text(f"SELECT COUNT(*) FROM {table} WHERE {demote_where}"), params).scalar() or 0)
            promoted[table] = int(db.execute(text(f"SELECT COUNT(*) FROM {table} WHERE {promote_where}"), params).scalar() or 0)
            continue
        demoted[table] = db.execute(
            text(f"UPDATE {table} SET authority_status = '{REFERENCE}', updated_at = :now WHERE {demote_where}"), params
        ).rowcount
        promoted[table] = db.execute(
            text(f"UPDATE {table} SET authority_status = '{AUTHORITATIVE}', updated_at = :now WHERE {promote_where}"),
            params,
        ).rowcount
    return promoted, demoted


KEEP_END = object()


def move_window(
    db: Session,
    *,
    broker_account_id: int,
    source_kind: str,
    fact_scope: str,
    effective_from: date,
    effective_to: date | None | object = KEEP_END,
    reason: str,
    actor: str,
    apply: bool = True,
) -> WindowMove:
    """The explicit, logged way to move (or close) a source's authority window.

    Restamps that source's facts on the broker account to match the new window
    and marks History dirty from the earliest affected date. With apply=False
    nothing is written; the result says what would change. Doesn't commit."""
    if not reason.strip():
        raise AuthorityWindowError("a reason is required to move an authority window")
    before = get_window(db, broker_account_id, source_kind, fact_scope)
    new_to: date | None
    if effective_to is KEEP_END:
        new_to = before.effective_to if before else None
    else:
        new_to = effective_to  # type: ignore[assignment]
    _check_dates(effective_from, new_to)
    _check_no_overlap(
        db,
        broker_account_id=broker_account_id,
        source_kind=source_kind,
        fact_scope=fact_scope,
        effective_from=effective_from,
        effective_to=new_to,
    )
    after = AuthorityWindow(
        id=before.id if before else 0,
        broker_account_id=broker_account_id,
        source_kind=source_kind,
        fact_scope=fact_scope,
        effective_from=effective_from,
        effective_to=new_to,
        authority_status=AUTHORITATIVE,
    )
    restamps = source_kind == FLEX_SOURCE_KIND and fact_scope == FLEX_FACT_SCOPE
    if not apply:
        promoted, demoted = _restamp_counts(db, after, count_only=True) if restamps else ({}, {})
        return WindowMove(before=before, after=after, rows_promoted=promoted, rows_demoted=demoted, applied=False)

    if before is None:
        ensure_window(
            db,
            broker_account_id=broker_account_id,
            source_kind=source_kind,
            fact_scope=fact_scope,
            effective_from=effective_from,
            effective_to=new_to,
            reason=reason,
            actor=actor,
        )
    else:
        db.execute(
            text(
                f"""
                UPDATE portfolio_source_authority_windows
                SET effective_from = :effective_from, effective_to = :effective_to,
                    authority_status = '{AUTHORITATIVE}'
                WHERE id = :id
                """
            ),
            {"id": before.id, "effective_from": effective_from, "effective_to": new_to},
        )
        _log_change(
            db,
            window_id=before.id,
            broker_account_id=broker_account_id,
            source_kind=source_kind,
            fact_scope=fact_scope,
            action="moved",
            old=before,
            new_from=effective_from,
            new_to=new_to,
            new_status=AUTHORITATIVE,
            reason=reason,
            actor=actor,
        )
    after = get_window(db, broker_account_id, source_kind, fact_scope)  # type: ignore[assignment]
    assert after is not None
    promoted, demoted = ({}, {})
    if restamps:
        try:
            promoted, demoted = _restamp_counts(db, after, count_only=False)
        except IntegrityError as exc:
            raise AuthorityWindowError(
                "restamping would leave two authoritative rows for the same key; nothing was changed"
            ) from exc
    affected_from = min(d for d in (effective_from, before.effective_from if before else None) if d is not None)
    legacy_account_id = db.execute(
        text("SELECT legacy_account_id FROM broker_accounts WHERE id = :id"), {"id": broker_account_id}
    ).scalar()
    if legacy_account_id is not None:
        mark_rollups_dirty(db, affected_from, account_id=int(legacy_account_id), reason="authority_window_moved")
    return WindowMove(before=before, after=after, rows_promoted=promoted, rows_demoted=demoted, applied=True)
