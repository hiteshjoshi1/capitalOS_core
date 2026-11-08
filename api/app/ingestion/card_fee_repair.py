"""Re-type stored card conversion-fee rows as FEE (#308).

Card parsers before #308 stored currency conversion / foreign transaction fee lines (Citi's
"CCY CONVERSION FEE") as EXPENSE, so the card's fees-and-interest total (#300) missed them.
For each card row of type EXPENSE whose merchant text is such a fee (``card_fees``):
type -> FEE, category -> CreditCard::Fee, and a new fingerprint for the new natural key
(type is part of it, D-35), computed as a fresh upload of the same file would. The row keeps
its id, so a category override and transfer links stay.

A row whose stored fingerprint can't be reproduced from its stored values is reported and left
alone (its key isn't the one this repair assumes). Rows with no fingerprint (imported before
#157) only change type and category. History is marked dirty from the earliest change (#138).
Dry run unless apply.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ingestion.card_fees import CARD_FEE_CATEGORY, is_conversion_fee
from app.ingestion.runner import _free_source_fingerprint, _source_fingerprint
from app.wealth_rollup_dirty import mark_rollups_dirty


def _ts_forms(ts: Any) -> list[Any]:
    """The timestamp as a parser may have produced it: tz-aware UTC (Citi, DBS) or naive (UOB),
    whichever way the database returned it."""
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts.replace(" ", "T"))
        except ValueError:
            return [ts]
    if not isinstance(ts, datetime):
        return [ts]
    aware = ts.astimezone(timezone.utc) if ts.tzinfo is not None else ts.replace(tzinfo=timezone.utc)
    return [aware, aware.replace(tzinfo=None)]


def _key_tx(row: Dict[str, Any], ts: Any, tx_type: str) -> Dict[str, Any]:
    return {
        "ts": ts,
        "type": tx_type,
        "amount": row["amount"],
        "currency": row["currency"],
        "merchant_counterparty": row["merchant_counterparty"],
    }


def stored_form(row: Dict[str, Any]) -> Optional[tuple[Any, int]]:
    """(ts form, occurrence) that reproduces the row's stored fingerprint, or None."""
    fp = row.get("source_fingerprint")
    if not fp:
        return None
    for ts in _ts_forms(row["ts"]):
        for occurrence in range(1, 11):
            if _source_fingerprint(int(row["account_id"]), _key_tx(row, ts, str(row["type"])), occurrence) == fp:
                return ts, occurrence
    return None


@dataclass
class FeeRepairResult:
    candidates: int = 0
    retyped: int = 0
    unreproducible: List[int] = field(default_factory=list)
    by_account: Dict[int, int] = field(default_factory=dict)
    earliest: Optional[date] = None


def repair_card_fees(db: Session, *, apply: bool) -> FeeRepairResult:
    rows = [
        dict(row)
        for row in db.execute(
            text(
                """
                SELECT t.id, t.account_id, t.ts, t.type, t.amount, t.currency, t.merchant_counterparty,
                       t.notes, t.source_fingerprint
                FROM transactions t
                JOIN accounts a ON a.id = t.account_id
                WHERE a.account_type = 'CREDIT_CARD' AND t.type = 'EXPENSE'
                ORDER BY t.account_id, t.ts, t.id
                """
            )
        ).mappings().all()
    ]
    result = FeeRepairResult()
    touched_accounts: Dict[int, date] = {}
    for row in rows:
        if not is_conversion_fee(row.get("merchant_counterparty")):
            continue
        result.candidates += 1
        new_fp = None
        new_notes = row.get("notes")
        if row.get("source_fingerprint"):
            form = stored_form(row)
            if form is None:
                result.unreproducible.append(int(row["id"]))
                continue
            ts, _occurrence = form
            if apply:
                key = _key_tx(row, ts, "FEE")
                same = db.execute(
                    text(
                        """
                        SELECT count(*) FROM transactions
                        WHERE account_id = :account AND id <> :id AND ts = :ts AND type = 'FEE'
                          AND amount = :amount AND currency = :currency
                          AND COALESCE(merchant_counterparty, '') = COALESCE(:merchant, '')
                        """
                    ),
                    {"account": row["account_id"], "id": row["id"], "ts": row["ts"], "amount": row["amount"],
                     "currency": row["currency"], "merchant": row["merchant_counterparty"]},
                ).scalar()
                new_fp = _free_source_fingerprint(db, int(row["account_id"]), key, int(same or 0) + 1)
                old = str(row["source_fingerprint"])
                notes = str(new_notes or "")
                new_notes = notes.replace(f"fp:{old}", f"fp:{new_fp}") if f"fp:{old}" in notes else notes
        result.retyped += 1
        account_id = int(row["account_id"])
        result.by_account[account_id] = result.by_account.get(account_id, 0) + 1
        first_form = _ts_forms(row["ts"])[0]
        day = first_form.date() if isinstance(first_form, datetime) else first_form
        touched_accounts[account_id] = min(day, touched_accounts.get(account_id, day))
        result.earliest = day if result.earliest is None else min(result.earliest, day)
        if apply:
            db.execute(
                text(
                    """
                    UPDATE transactions
                    SET type = 'FEE', category = :category,
                        source_fingerprint = COALESCE(:fp, source_fingerprint), notes = :notes
                    WHERE id = :id
                    """
                ),
                {"category": CARD_FEE_CATEGORY, "fp": new_fp, "notes": new_notes, "id": row["id"]},
            )
    if apply and touched_accounts:
        for account_id, day in touched_accounts.items():
            mark_rollups_dirty(db, day, account_id=account_id, reason="card_fee_repair")
        db.commit()
    return result


def summary_lines(result: FeeRepairResult, *, applied: bool) -> List[str]:
    lines = [
        f"Card conversion-fee rows stored as spending: {result.candidates}; "
        f"{'re-typed' if applied else 'to re-type'} as fees: {result.retyped}"
        + (f" (by card account: {', '.join(f'{k}: {v}' for k, v in sorted(result.by_account.items()))})" if result.by_account else ""),
    ]
    if result.unreproducible:
        lines.append(f"Left alone (stored fingerprint not reproducible): {len(result.unreproducible)} rows, ids {result.unreproducible}")
    if result.earliest:
        lines.append(f"History {'marked dirty' if applied else 'would be marked dirty'} from {result.earliest.isoformat()}")
    lines.append("Applied." if applied else "Dry run: nothing changed. APPLY=1 to write.")
    return lines
