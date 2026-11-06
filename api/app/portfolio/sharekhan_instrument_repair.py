"""Repair Sharekhan instruments imported with ticker and name swapped (#222).

Sharekhan's holdings export labels its first two columns ``SKScripCode | Stock
Name`` but each row holds the company name first and the scrip code second.
Until the parser learnt that, every Sharekhan instrument was stored with the
company name as ``symbol`` and the scrip code as ``description``, and (being
imported before uploads linked instruments to ``assets``) with no asset. The
quote refresh prices assets only, so these holdings were never priced.

For each SHAREKHAN ``broker_instruments`` row this:

- swaps ``symbol`` / ``description`` when the upload it came from had them
  swapped. As in the parser, that's decided per upload (import run), not per
  row: the run's rows vote (a name has spaces, a scrip code doesn't), so a
  one-word company name is swapped along with its neighbours. A row in no
  upload is swapped when its symbol isn't a ticker and its description is;
- renames the synthetic ``broker_instrument_id`` to ``<TICKER>_<CCY>``, what a
  fixed upload of the same holding looks up, so the next upload reuses the row
  instead of adding a second one. The row's ``id`` never changes (position
  snapshots reference it). If a row with that id already exists (a holding
  uploaded after the parser fix), the old id is kept and the row is reported;
- links the row to the ``assets`` row for (ticker, currency), creating it
  (home country IN) if needed, so the NSE refresh maps and prices it;
- sets ``country`` IN on INR rows that have none.

A row that should be swapped but whose description isn't a ticker is left
alone, reported as ``ambiguous``. History is marked
dirty per account from the earliest snapshot of a changed instrument. Dry run
unless ``apply``; a second run changes nothing. Reports counts, never holdings.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ingestion.parsers.sharekhan_holdings_xls_v1 import code_and_name_swapped
from app.market_data.service import _ticker_candidate
from app.portfolio.upload_canonical import _get_or_create_asset
from app.wealth_rollup_dirty import mark_rollups_dirty

PLATFORM_CODE = "SHAREKHAN"


@dataclass
class InstrumentOutcome:
    instrument_id: int
    action: str  # repaired | unchanged | ambiguous
    swapped: bool = False
    id_renamed: bool = False
    id_collision: bool = False
    asset_linked: bool = False
    asset_created: bool = False
    country_set: bool = False


@dataclass
class RepairResult:
    applied: bool
    instruments: list[InstrumentOutcome] = field(default_factory=list)
    dirty_from: dict[int, date] = field(default_factory=dict)

    def count(self, attr: str) -> int:
        return sum(1 for item in self.instruments if getattr(item, attr))

    def actions(self) -> Counter[str]:
        return Counter(item.action for item in self.instruments)


def _resolve_ticker_and_name(
    symbol: str | None, description: str | None, *, swapped_upload: bool
) -> tuple[str, str, bool] | None:
    """(ticker, name, swapped), or None when the row can't be resolved."""
    sym_ticker = _ticker_candidate(symbol)
    desc_ticker = _ticker_candidate(description)
    if swapped_upload or (sym_ticker is None and desc_ticker is not None):
        if desc_ticker is None:
            return None
        return desc_ticker, str(symbol or "").strip() or desc_ticker, True
    if sym_ticker is None:
        return None
    return sym_ticker, str(description or "").strip() or sym_ticker, False


def _swapped_instrument_ids(db: Session, rows: list[dict[str, Any]]) -> set[int]:
    """Instruments in an upload whose rows, as stored now, vote "swapped"."""
    by_id = {int(row["id"]): row for row in rows}
    links = db.execute(
        text(
            """
            SELECT DISTINCT ps.import_run_id, ps.broker_instrument_id
            FROM portfolio_position_snapshots ps
            JOIN broker_instruments bi ON bi.id = ps.broker_instrument_id
            WHERE bi.platform_code = :platform_code
            """
        ),
        {"platform_code": PLATFORM_CODE},
    ).fetchall()
    runs: dict[Any, list[int]] = {}
    for run_id, instrument_id in links:
        if int(instrument_id) in by_id:
            runs.setdefault(run_id, []).append(int(instrument_id))
    swapped: set[int] = set()
    for instrument_ids in runs.values():
        pairs = [(by_id[i]["symbol"], by_id[i]["description"]) for i in instrument_ids]
        if code_and_name_swapped(pairs):
            swapped.update(instrument_ids)
    return swapped


def _asset_id_for(db: Session, ticker: str, currency: str) -> int | None:
    row = db.execute(
        text("SELECT id FROM assets WHERE symbol = :symbol AND quote_currency = :currency LIMIT 1"),
        {"symbol": ticker, "currency": currency},
    ).fetchone()
    return int(row[0]) if row else None


def _id_taken(db: Session, row: dict[str, Any], broker_instrument_id: str) -> bool:
    found = db.execute(
        text(
            """
            SELECT 1 FROM broker_instruments
            WHERE platform_code = :platform_code
              AND broker_instrument_id = :broker_instrument_id
              AND COALESCE(listing_exchange, '') = COALESCE(:listing_exchange, '')
              AND COALESCE(currency, '') = COALESCE(:currency, '')
              AND id <> :id
            LIMIT 1
            """
        ),
        {
            "platform_code": PLATFORM_CODE,
            "broker_instrument_id": broker_instrument_id,
            "listing_exchange": row["listing_exchange"],
            "currency": row["currency"],
            "id": row["id"],
        },
    ).fetchone()
    return found is not None


def _earliest_snapshot_by_account(db: Session, instrument_ids: list[int]) -> dict[int, date]:
    if not instrument_ids:
        return {}
    placeholders = ",".join(str(int(i)) for i in sorted(instrument_ids))
    rows = db.execute(
        text(
            f"""
            SELECT ba.legacy_account_id, MIN(ps.report_date)
            FROM portfolio_position_snapshots ps
            JOIN broker_accounts ba ON ba.id = ps.broker_account_id
            WHERE ps.broker_instrument_id IN ({placeholders})
              AND ba.legacy_account_id IS NOT NULL
            GROUP BY ba.legacy_account_id
            """
        )
    ).fetchall()
    out: dict[int, date] = {}
    for account_id, earliest in rows:
        if earliest is None:
            continue
        out[int(account_id)] = earliest if isinstance(earliest, date) else date.fromisoformat(str(earliest)[:10])
    return out


def repair_sharekhan_instruments(db: Session, *, apply: bool) -> RepairResult:
    result = RepairResult(applied=apply)
    fetched = db.execute(
        text(
            """
            SELECT id, broker_instrument_id, symbol, description, security_type,
                   listing_exchange, currency, country, asset_id
            FROM broker_instruments
            WHERE platform_code = :platform_code
            ORDER BY id
            """
        ),
        {"platform_code": PLATFORM_CODE},
    ).mappings().all()

    rows = [dict(raw) for raw in fetched]
    swapped_ids = _swapped_instrument_ids(db, rows)
    changed_ids: list[int] = []
    for row in rows:
        instrument_id = int(row["id"])
        resolved = _resolve_ticker_and_name(
            row["symbol"], row["description"], swapped_upload=instrument_id in swapped_ids
        )
        if resolved is None:
            result.instruments.append(InstrumentOutcome(instrument_id, "ambiguous"))
            continue
        ticker, name, swapped = resolved
        currency = str(row["currency"] or "INR").strip().upper()
        outcome = InstrumentOutcome(instrument_id, "unchanged", swapped=swapped)
        updates: dict[str, Any] = {}
        if row["symbol"] != ticker:
            updates["symbol"] = ticker
        if swapped or not row["description"]:
            updates["description"] = name

        target_id = f"{ticker}_{currency}"
        if row["broker_instrument_id"] != target_id:
            if _id_taken(db, row, target_id):
                outcome.id_collision = True
            else:
                updates["broker_instrument_id"] = target_id
                outcome.id_renamed = True

        if currency == "INR" and not row["country"]:
            updates["country"] = "IN"
            outcome.country_set = True

        if row["asset_id"] is None:
            asset_id = _asset_id_for(db, ticker, currency)
            if asset_id is None:
                outcome.asset_created = True
                if apply:
                    asset_id = _get_or_create_asset(
                        db,
                        symbol=ticker,
                        currency=currency,
                        name=name,
                        asset_class=row["security_type"] or "STOCK",
                        home_country="IN" if currency == "INR" else None,
                    )
            outcome.asset_linked = True
            if asset_id is not None:
                updates["asset_id"] = asset_id

        if not updates and not outcome.asset_linked:
            result.instruments.append(outcome)
            continue
        outcome.action = "repaired"
        result.instruments.append(outcome)
        changed_ids.append(instrument_id)
        if apply and updates:
            assignments = ", ".join(f"{column} = :{column}" for column in updates)
            db.execute(
                text(f"UPDATE broker_instruments SET {assignments}, updated_at = :updated_at WHERE id = :id"),
                {**updates, "updated_at": datetime.now(tz=timezone.utc), "id": instrument_id},
            )

    result.dirty_from = _earliest_snapshot_by_account(db, changed_ids)
    if apply:
        for account_id, earliest in sorted(result.dirty_from.items()):
            mark_rollups_dirty(db, earliest, account_id=account_id, reason="sharekhan instrument repair (#222)")
        db.commit()
    else:
        db.rollback()
    return result


def summary_lines(result: RepairResult) -> list[str]:
    actions = result.actions()
    mode = "APPLIED" if result.applied else "DRY RUN (APPLY=1 to write)"
    lines = [
        f"Sharekhan instrument repair (#222): {mode}",
        f"  instruments: {len(result.instruments)}"
        f" (repaired {actions.get('repaired', 0)}, unchanged {actions.get('unchanged', 0)},"
        f" ambiguous {actions.get('ambiguous', 0)})",
        f"  ticker/name swapped: {result.count('swapped')}",
        f"  broker_instrument_id renamed: {result.count('id_renamed')}"
        f" (kept because the new id exists: {result.count('id_collision')})",
        f"  linked to an asset: {result.count('asset_linked')} (assets created: {result.count('asset_created')})",
        f"  country set to IN: {result.count('country_set')}",
    ]
    for item in result.instruments:
        if item.action == "ambiguous" or item.id_collision:
            lines.append(f"  check instrument id {item.instrument_id}: {item.action}{' (id collision)' if item.id_collision else ''}")
    if result.dirty_from:
        for account_id, earliest in sorted(result.dirty_from.items()):
            lines.append(f"  History {'marked' if result.applied else 'to mark'} dirty: account {account_id} from {earliest.isoformat()}")
    return lines
