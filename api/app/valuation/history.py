"""History (D-29): the wealth_monthly_rollups rows behind the timeline, their
lazy recompute from dirty marks (#138), and month-on-month changes."""
from __future__ import annotations

from decimal import Decimal

import json
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import account_scope_sql
from app.core.clock import use_timezone
from app.services.user_preferences import effective_timezone
from app.valuation import clock
from app.valuation.clock import _add_months, _anchor_ts, _date_only, _iso_value, _latest_completed_month_start, _normalize_ts, _parse_month
from app.valuation.facts import _networth_components
from app.valuation.state import _crypto_snapshot_coverage_as_of, _effective_as_of
from app.wealth_rollup_dirty import dirty_state, dirty_user_ids, settle_dirty_mark
from app.valuation.money import D, ZERO


# ─── Wealth Timeline rollups (Phase 2) ──────────────────────────────────────
#
# wealth_monthly_rollups pre-aggregates one net-worth snapshot per
# (user, month, base_currency) so the History page is a single indexed read
# instead of recomputing _networth_components per month on every request.
# Only completed months (own anchor passed) are stored. Rows are written by
# _refresh_wealth_rollups: forced by the backfill endpoint ("Generate history"),
# and lazily by the timeline GET / scheduler hook for rows that went stale
# (#138, app.wealth_rollup_dirty).

_WEALTH_ROLLUP_CARRY_HORIZON_DAYS = 180
_DAILY_CADENCE_PLATFORMS = {"IBKR", "CRYPTO", "COINBASE"}
_DAILY_CADENCE_FRESH_DAYS = 3
_MANUAL_CADENCE_FRESH_DAYS = 31



def _db_money(value: Any, is_postgres: bool) -> Any:
    """A Decimal amount as a bound parameter: exact on Postgres (NUMERIC); SQLite's
    driver takes no Decimal, so a Decimal there (tests)."""
    return D(value) if is_postgres else float(D(value))

def _platform_cadence_days(platform: str | None) -> int:
    return _DAILY_CADENCE_FRESH_DAYS if (platform or "").upper() in _DAILY_CADENCE_PLATFORMS else _MANUAL_CADENCE_FRESH_DAYS


def _freshness_bucket_and_days(
    as_of: date | None,
    anchor_date: date,
    cadence_days: int,
) -> tuple[str, Optional[int]]:
    """Bucket one source's staleness at a historical anchor: fresh/carried/missing.

    "stale" (a normally-daily source gone quiet) isn't distinguishable from
    "carried" with only a single as_of date, so daily and manual sources share
    this three-way bucket; the cadence threshold is what differs between them.
    """
    if as_of is None:
        return "missing", None
    days = (anchor_date - as_of).days
    if days < 0:
        return "missing", None
    if days <= cadence_days:
        return "fresh", days
    if days <= _WEALTH_ROLLUP_CARRY_HORIZON_DAYS:
        return "carried", days
    return "missing", days


def _platform_freshness_entries(
    rows: Dict[str, Any],
    anchor_date: date,
    crypto_as_of: Optional[date],
) -> list[dict[str, Any]]:
    nav_account_ids = {
        int(row["legacy_account_id"])
        for row in rows.get("nav", [])
        if row.get("legacy_account_id") is not None
    }
    latest_by_platform: Dict[str, date] = {}

    def _note(platform: Optional[str], value: Any) -> None:
        if value is None:
            return
        as_of = date.fromisoformat(value) if isinstance(value, str) else value
        key = platform or "UNKNOWN"
        if key not in latest_by_platform or as_of > latest_by_platform[key]:
            latest_by_platform[key] = as_of

    for row in rows.get("positions", []):
        _note(row.get("platform"), row.get("report_date"))
    for row in rows.get("nav", []):
        _note(row.get("platform"), row.get("report_date"))
    for row in rows.get("cash", []):
        if row.get("account_id") is not None and int(row["account_id"]) in nav_account_ids:
            continue
        _note(row.get("platform"), row.get("as_of_date"))

    entries: list[dict[str, Any]] = []
    for platform, as_of in latest_by_platform.items():
        status, days_old = _freshness_bucket_and_days(as_of, anchor_date, _platform_cadence_days(platform))
        entries.append({
            "platform": platform,
            "as_of": as_of.isoformat(),
            "days_old": days_old,
            "status": status,
        })
    if crypto_as_of is not None:
        status, days_old = _freshness_bucket_and_days(crypto_as_of, anchor_date, _DAILY_CADENCE_FRESH_DAYS)
        entries.append({
            "platform": "CRYPTO",
            "as_of": crypto_as_of.isoformat(),
            "days_old": days_old,
            "status": status,
        })
    entries.sort(key=lambda e: e["platform"])
    return entries


_FRESHNESS_STATUS_RANK = {"fresh": 0, "carried": 1, "stale": 2, "missing": 3}


def _worst_freshness_status(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return "missing"
    return max((e["status"] for e in entries), key=lambda s: _FRESHNESS_STATUS_RANK.get(s, 3))


def _wealth_rollup_row(
    db: Session,
    anchor_ts: datetime,
    base_currency: str,
    current_user_id: int,
) -> Dict[str, Any]:
    """Compute one month's rollup row. Snapshot-consistent values only
    (price_overlay=False) — the timeline never mixes live-priced "now" values
    into a historical point; "now" is rendered as a separate provisional marker."""
    components, rows = _networth_components(
        db, anchor_ts, base_currency, current_user_id, price_overlay=False, return_rows=True,
    )
    crypto_as_of = _crypto_snapshot_coverage_as_of(db, anchor_ts.date(), current_user_id)
    source_freshness = _platform_freshness_entries(rows, anchor_ts.date(), crypto_as_of)
    return {
        "anchor_date": anchor_ts.date(),
        "components": components,
        "source_freshness": source_freshness,
        "freshness_status": _worst_freshness_status(source_freshness),
    }


def _upsert_wealth_rollup(
    db: Session,
    current_user_id: int,
    month: str,
    base_currency: str,
    row: Dict[str, Any],
    *,
    input_generation: int = 0,
) -> None:
    components = row["components"]
    # SQLite (used by the test suite) has no JSONB type or NOW(); Postgres gets
    # the real cast, SQLite gets the plain bound string / a Python-side timestamp.
    is_postgres = bool(db.bind and db.bind.dialect.name == "postgresql")
    json_cast = "CAST(:source_freshness AS JSONB)" if is_postgres else ":source_freshness"
    computed_at = datetime.now(tz=timezone.utc)
    db.execute(
        text(
            f"""
            INSERT INTO wealth_monthly_rollups
              (user_id, month, anchor_date, base_currency, total, cash, stocks_funds, crypto,
               liabilities, source_freshness, freshness_status, computed_at, input_generation)
            VALUES
              (:user_id, :month, :anchor_date, :base_currency, :total, :cash, :stocks_funds, :crypto,
               :liabilities, {json_cast}, :freshness_status, :computed_at, :input_generation)
            ON CONFLICT (user_id, month, base_currency) DO UPDATE SET
              anchor_date = EXCLUDED.anchor_date,
              total = EXCLUDED.total,
              cash = EXCLUDED.cash,
              stocks_funds = EXCLUDED.stocks_funds,
              crypto = EXCLUDED.crypto,
              liabilities = EXCLUDED.liabilities,
              source_freshness = EXCLUDED.source_freshness,
              freshness_status = EXCLUDED.freshness_status,
              computed_at = EXCLUDED.computed_at,
              input_generation = EXCLUDED.input_generation
            """
        ),
        {
            "user_id": current_user_id,
            "month": month,
            "anchor_date": row["anchor_date"],
            "base_currency": base_currency,
            "total": _db_money(components["total"], is_postgres),
            "cash": _db_money(components["cash"], is_postgres),
            "stocks_funds": _db_money(components["stocks_funds"], is_postgres),
            "crypto": _db_money(components["crypto"], is_postgres),
            "liabilities": _db_money(components["liabilities"], is_postgres),
            "source_freshness": json.dumps(row["source_freshness"]),
            "freshness_status": row["freshness_status"],
            "computed_at": computed_at,
            "input_generation": input_generation,
        },
    )


def _rollup_month_completed(month_start: datetime) -> bool:
    """A month gets a stored rollup row only once its own anchor has passed.
    The still-open month is covered by the timeline's live "now" point (#138)."""
    return clock._anchor_passed(_anchor_ts(month_start))


def _delete_wealth_rollup(db: Session, current_user_id: int, month: str, base_currency: str) -> None:
    db.execute(
        text(
            "DELETE FROM wealth_monthly_rollups "
            "WHERE user_id = :user_id AND month = :month AND base_currency = :base_currency"
        ),
        {"user_id": current_user_id, "month": month, "base_currency": base_currency},
    )


def _refresh_wealth_rollups(
    db: Session,
    current_user_id: int,
    base_currency: str,
    *,
    months: Optional[list[str]] = None,
    force: bool = False,
    on_month: Optional[Callable[[int, int, str], None]] = None,
) -> Dict[str, int]:
    """Bring stored rollup rows up to date (#138). Commits only if it wrote.

    For each month considered (``months``, or every stored month when None):
    - not completed yet (its own anchor is in the future): a stored row is a
      provisional one, written by the old rule at last month's anchor. Deleted.
    - completed: (re)computed at its own anchor when ``force``; when missing
      (only for ``months``, and only from the user's first stored month on, so
      a read never generates history the user hasn't asked for); when stored at
      another anchor (the old rule, or a SNAPSHOT_DAY change); or when a dirty
      mark covers its anchor and the row predates that mark.
    Then the user's dirty mark is settled (app.wealth_rollup_dirty).
    ``on_month(done, total, month)`` is called before each considered month (#292's
    progress: ``done`` months finished so far).
    """
    dirty_from, generation = dirty_state(db, current_user_id)
    stored = {
        str(row["month"]): row
        for row in db.execute(
            text(
                "SELECT month, anchor_date, input_generation FROM wealth_monthly_rollups "
                "WHERE user_id = :user_id AND base_currency = :base_currency"
            ),
            {"user_id": current_user_id, "base_currency": base_currency},
        ).mappings().all()
    }
    first_stored = min(stored) if stored else None
    candidates = sorted(set(months) if months is not None else set(stored))

    written = 0
    deleted = 0
    for index, month_key in enumerate(candidates):
        if on_month is not None:
            on_month(index, len(candidates), month_key)
        month_start = _parse_month(month_key)
        row = stored.get(month_key)
        if not _rollup_month_completed(month_start):
            if row is not None:
                _delete_wealth_rollup(db, current_user_id, month_key, base_currency)
                deleted += 1
            continue
        anchor = _anchor_ts(month_start)
        if row is None:
            needed = force or (months is not None and first_stored is not None and month_key >= first_stored)
        else:
            needed = (
                force
                or _date_only(row["anchor_date"]) != anchor.date()
                or (
                    dirty_from is not None
                    and anchor.date() >= dirty_from
                    and int(row["input_generation"] or 0) < generation
                )
            )
        if not needed:
            continue
        computed = _wealth_rollup_row(db, anchor, base_currency, current_user_id)
        _upsert_wealth_rollup(
            db, current_user_id, month_key, base_currency, computed, input_generation=generation,
        )
        written += 1

    settled = settle_dirty_mark(db, current_user_id, generation) if (written or dirty_from is not None) else False
    if written or deleted or settled:
        db.commit()
    return {"written": written, "deleted": deleted}


def _trailing_month_keys(months: int) -> list[str]:
    current_month_start = _parse_month(clock._current_anchor_ts().strftime("%Y-%m"))
    return [_add_months(current_month_start, offset).strftime("%Y-%m") for offset in range(-(months - 1), 1)]


def _backfill_wealth_rollups(
    db: Session,
    current_user_id: int,
    base_currency: str,
    months: int,
) -> int:
    """Recompute every completed month of the trailing N (the "Generate
    history" button). Returns the number of rows written."""
    result = _refresh_wealth_rollups(
        db, current_user_id, base_currency, months=_trailing_month_keys(months), force=True,
    )
    return result["written"]


def refresh_dirty_wealth_rollups(db: Session) -> int:
    """Scheduler hook (after IBKR Flex / crypto jobs): recompute every stale
    stored row of every user with a pending dirty mark, in each base currency
    that user has rows in. Returns the number of rows written."""
    written = 0
    for user_id in dirty_user_ids(db):
        # Which months are completed follows each user's home timezone (#202).
        with use_timezone(effective_timezone(db, user_id)):
            written += _refresh_dirty_rollups_for_user(db, user_id)
    return written


def _refresh_dirty_rollups_for_user(db: Session, user_id: int) -> int:
    currencies = [
        str(row[0])
        for row in db.execute(
            text("SELECT DISTINCT base_currency FROM wealth_monthly_rollups WHERE user_id = :user_id"),
            {"user_id": user_id},
        ).fetchall()
    ]
    if not currencies:
        if settle_dirty_mark(db, user_id, dirty_state(db, user_id)[1]):
            db.commit()
        return 0
    return sum(_refresh_wealth_rollups(db, user_id, currency)["written"] for currency in currencies)


def _timeline_upload_markers(
    db: Session,
    current_user_id: int,
    since_month_start: datetime,
) -> Dict[str, list[str]]:
    """Months where a manual statement import completed, for the timeline's
    upload-marker ticks. Keyed by 'YYYY-MM' -> list of platform codes."""
    rows = db.execute(
        text(
            """
            SELECT ij.platform, ij.created_at
            FROM import_jobs ij
            JOIN accounts a ON a.id = ij.account_id
            WHERE ij.status = 'IMPORTED'
              AND ij.created_at >= :since
              AND """
            + account_scope_sql("a")
        ),
        {"since": since_month_start, "current_user_id": current_user_id},
    ).mappings().all()
    markers: Dict[str, set[str]] = {}
    for row in rows:
        created_at = _normalize_ts(row["created_at"])
        if created_at is None:
            continue
        month_key = created_at.strftime("%Y-%m")
        markers.setdefault(month_key, set()).add(str(row["platform"] or "").upper())
    return {month: sorted(platforms) for month, platforms in markers.items()}


def _stored_timeline_points(
    db: Session,
    current_user_id: int,
    base_currency: str,
    range_start: datetime,
) -> tuple[list[dict[str, Any]], Dict[str, list[str]]]:
    """The stored History rows from ``range_start``'s month on (one indexed
    scan), and the upload markers by month."""
    rollup_rows = db.execute(
        text(
            """
            SELECT month, anchor_date, total, cash, stocks_funds, crypto, liabilities,
                   source_freshness, freshness_status, computed_at
            FROM wealth_monthly_rollups
            WHERE user_id = :user_id AND base_currency = :base_currency AND month >= :from_month
            ORDER BY month ASC
            """
        ),
        {
            "user_id": current_user_id,
            "base_currency": base_currency,
            "from_month": range_start.strftime("%Y-%m"),
        },
    ).mappings().all()

    upload_markers = _timeline_upload_markers(db, current_user_id, range_start)

    points = []
    for row in rollup_rows:
        source_freshness = row["source_freshness"]
        if isinstance(source_freshness, str):
            source_freshness = json.loads(source_freshness)
        anchor_date = row["anchor_date"]
        points.append({
            "month": row["month"],
            "anchor_date": anchor_date if isinstance(anchor_date, str) else anchor_date.isoformat(),
            "total": D(row["total"]),
            "cash": D(row["cash"]),
            "stocks_funds": D(row["stocks_funds"]),
            "crypto": D(row["crypto"]),
            "liabilities": D(row["liabilities"]),
            "source_freshness": source_freshness,
            "freshness_status": row["freshness_status"],
            "computed_at": _iso_value(row["computed_at"]),
            "uploads": upload_markers.get(row["month"], []),
        })
    return points, upload_markers


def _cached_networth_components(
    db: Session,
    anchor: datetime,
    base_currency: str,
    current_user_id: int,
    nw_cache: Optional[Dict[datetime, Dict[str, Decimal]]],
) -> Dict[str, Decimal]:
    """Snapshot-mode _networth_components, memoised per request by anchor."""
    if nw_cache is None:
        return _networth_components(db, anchor, base_currency, current_user_id)
    if anchor not in nw_cache:
        nw_cache[anchor] = _networth_components(db, anchor, base_currency, current_user_id)
    return nw_cache[anchor]


def baseline_missing(compare_as_of: Any, compare_value: Decimal) -> bool:
    """No data at all for a comparison (#224): nothing at or before its anchor,
    so its value is a placeholder zero, not a real one. Callers show
    "no data for <month>" instead of a delta the size of the whole figure."""
    return compare_as_of is None and abs(D(compare_value)) < Decimal("1e-9")


def _snapshot_compare_months(snapshot_month_start: datetime, compare_set: set[str]) -> Dict[str, datetime]:
    """Comparison months for a value taken at `snapshot_month_start`'s anchor:
    the completed anchor one month and twelve months before it (#133)."""
    months: Dict[str, datetime] = {}
    if "prev_month" in compare_set:
        months["vs_prev_month"] = _add_months(snapshot_month_start, -1)
    if "prev_year" in compare_set:
        months["vs_prev_year"] = _add_months(snapshot_month_start, -12)
    return months


def _live_compare_months(now: datetime, compare_set: set[str]) -> Dict[str, datetime]:
    """Comparison months for a live value at `now`: the latest completed
    month-end (vs_prev_month) and the same month-end a year earlier (#133)."""
    latest = _latest_completed_month_start(now)
    months: Dict[str, datetime] = {}
    if "prev_month" in compare_set:
        months["vs_prev_month"] = latest
    if "prev_year" in compare_set:
        months["vs_prev_year"] = _add_months(latest, -12)
    return months


def _compute_net_worth_changes(
    db: Session,
    compare_months: Dict[str, datetime],
    as_of: datetime | None,
    current_value: Decimal,
    base_currency: str,
    current_user_id: int,
    value_selector: Callable[[Dict[str, Decimal]], Decimal] = lambda nw: nw["total"],
    nw_cache: Optional[Dict[datetime, Dict[str, Decimal]]] = None,
) -> Dict[str, Dict[str, Any]]:
    """`current_value` vs each comparison month's completed anchor. Build
    `compare_months` with _snapshot_compare_months (a value taken at a month's
    anchor) or _live_compare_months (a live value), so every comparison is
    like for like (#133).
    """
    changes: Dict[str, Dict[str, Any]] = {}

    def _delta(label: str, other_month_start: datetime):
        other_anchor = _anchor_ts(other_month_start)
        other_as_of = _effective_as_of(db, other_anchor, current_user_id)
        other_nw = _cached_networth_components(db, other_anchor, base_currency, current_user_id, nw_cache)
        prev_value = value_selector(other_nw)

        abs_change = current_value - prev_value
        pct_change = (abs_change / prev_value) if prev_value > 0 else None

        changes[label] = {
            "abs": abs_change,
            "pct": pct_change,
            "current_as_of": as_of.isoformat() if as_of else None,
            "compare_as_of": other_as_of.isoformat() if other_as_of else None,
            "compare_month": other_month_start.strftime("%Y-%m"),
            "compare_value": prev_value,
            "baseline_missing": baseline_missing(other_as_of, prev_value),
        }

    for label, other_month_start in compare_months.items():
        _delta(label, other_month_start)

    return changes


def _compute_component_changes(
    db: Session,
    month_start: datetime,
    as_of: datetime | None,
    current_components: Dict[str, Decimal],
    base_currency: str,
    current_user_id: int,
    nw_cache: Optional[Dict[datetime, Dict[str, Decimal]]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Per-component change vs the completed anchor one month before
    `month_start` (the month the current components were taken at, #133)."""
    prior_month_start = _add_months(month_start, -1)
    prior_anchor = _anchor_ts(prior_month_start)
    prior_as_of = _effective_as_of(db, prior_anchor, current_user_id)
    prior_components = _cached_networth_components(db, prior_anchor, base_currency, current_user_id, nw_cache)

    out: Dict[str, Dict[str, Any]] = {}
    for key in ("cash", "stocks_funds", "crypto"):
        current_value = current_components[key]
        prior_value = prior_components[key]
        abs_change = current_value - prior_value
        out[key] = {
            "abs": abs_change,
            "pct": (abs_change / prior_value) if prior_value > 0 else None,
            "current_as_of": as_of.isoformat() if as_of else None,
            "compare_as_of": prior_as_of.isoformat() if prior_as_of else None,
            "compare_month": prior_month_start.strftime("%Y-%m"),
            "compare_value": prior_value,
            "baseline_missing": baseline_missing(prior_as_of, prior_value),
        }
    return out


