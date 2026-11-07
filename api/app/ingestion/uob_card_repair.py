"""Repair UOB card rows imported before #299's parser fix.

Two parser bugs, both in ``uob_credit_card_xls_v1``:
- an undated "Previous Balance" line was merged into the transaction above it, so that
  transaction was stored with the previous balance as its amount (and type/category);
- the export can print the latest statement period twice, and both copies were stored.

For each UOB card upload whose raw file is kept, the fixed parser's rows are matched
against the stored rows of that upload:
1. same day, merchant, currency and amount: kept as is;
2. same day, merchant and currency, different amount: the stored row is corrected in place
   (amount, type, category, fingerprint), so its id, category override and transfer links stay;
3. stored rows left over are duplicates: deleted, after moving a category override onto the
   kept twin when the twin has none.
Rows the fixed parser has that match nothing are reported, never inserted (re-upload instead).
History is marked dirty from the earliest changed date (#138). Dry run unless apply.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ingestion.parsers.uob_credit_card_xls_v1 import parse_uob_credit_card_xls
from app.ingestion.runner import _compose_notes, _free_source_fingerprint, _natural_key
from app.wealth_rollup_dirty import mark_rollups_dirty

PARSER_KEY = "uob_credit_card_xls_v1"


def _day(ts: Any) -> date:
    if isinstance(ts, datetime):
        if ts.tzinfo is not None:
            ts = ts.astimezone(timezone.utc)
        return ts.date()
    return ts


def _cents(amount: Any) -> int:
    return int(round(float(amount) * 100))


def _loose(day: date, merchant: Any, currency: Any) -> tuple[Any, ...]:
    return (day, (merchant or "").strip(), (currency or "").upper())


@dataclass
class Plan:
    keep: List[int] = field(default_factory=list)
    # (stored id, parsed tx)
    fix: List[tuple[int, Dict[str, Any]]] = field(default_factory=list)
    # (stored id, kept twin id or None)
    delete: List[tuple[int, Optional[int]]] = field(default_factory=list)
    unmatched_parsed: List[Dict[str, Any]] = field(default_factory=list)


def plan_job(stored: List[Dict[str, Any]], parsed: List[Dict[str, Any]]) -> Plan:
    """Match one upload's stored rows (id, ts, amount, currency, merchant_counterparty)
    against the fixed parser's rows. Pure: no database."""
    plan = Plan()
    free = {int(row["id"]): row for row in sorted(stored, key=lambda r: int(r["id"]))}
    matched_to: Dict[int, int] = {}  # parsed index -> stored id

    # 1. exact matches
    for i, tx in enumerate(parsed):
        key = (*_loose(_day(tx["ts"]), tx.get("merchant_counterparty"), tx.get("currency")), _cents(tx["amount"]))
        for sid, row in free.items():
            if (*_loose(_day(row["ts"]), row.get("merchant_counterparty"), row.get("currency")), _cents(row["amount"])) == key:
                matched_to[i] = sid
                plan.keep.append(sid)
                del free[sid]
                break

    # 2. same day / merchant / currency, wrong amount: correct in place
    for i, tx in enumerate(parsed):
        if i in matched_to:
            continue
        loose = _loose(_day(tx["ts"]), tx.get("merchant_counterparty"), tx.get("currency"))
        for sid, row in free.items():
            if _loose(_day(row["ts"]), row.get("merchant_counterparty"), row.get("currency")) == loose:
                matched_to[i] = sid
                plan.fix.append((sid, tx))
                del free[sid]
                break
        else:
            plan.unmatched_parsed.append(tx)

    # 3. the rest are duplicates of a kept row
    kept_ids = set(plan.keep)
    kept_rows = {int(row["id"]): row for row in stored if int(row["id"]) in kept_ids}
    for sid, row in free.items():
        key = (*_loose(_day(row["ts"]), row.get("merchant_counterparty"), row.get("currency")), _cents(row["amount"]))
        twin = next(
            (
                kid for kid, krow in kept_rows.items()
                if (*_loose(_day(krow["ts"]), krow.get("merchant_counterparty"), krow.get("currency")), _cents(krow["amount"])) == key
            ),
            None,
        )
        plan.delete.append((sid, twin))
    return plan


@dataclass
class JobResult:
    job_id: int
    account_id: int
    stored: int
    parsed: int
    keep: int
    fix: int
    delete: int
    overrides_moved: int = 0
    unmatched_parsed: int = 0
    missing_file: bool = False
    earliest_change: Optional[date] = None


def repair_uob_card_rows(db: Session, *, apply: bool, data_root: str = "/app") -> List[JobResult]:
    jobs = db.execute(
        text(
            """
            SELECT id, account_id, stored_path
            FROM import_jobs
            WHERE parser_key = :parser AND removed_at IS NULL
            ORDER BY id
            """
        ),
        {"parser": PARSER_KEY},
    ).mappings().all()
    results: List[JobResult] = []
    for job in jobs:
        path = str(job["stored_path"] or "")
        if path and not os.path.isabs(path):
            path = os.path.join(data_root, path)
        stored = [
            dict(row)
            for row in db.execute(
                text(
                    """
                    SELECT id, ts, type, amount, currency, merchant_counterparty
                    FROM transactions WHERE import_job_id = :job ORDER BY id
                    """
                ),
                {"job": int(job["id"])},
            ).mappings().all()
        ]
        result = JobResult(int(job["id"]), int(job["account_id"]), len(stored), 0, 0, 0, 0)
        if not path or not os.path.exists(path):
            result.missing_file = True
            results.append(result)
            continue
        parsed = parse_uob_credit_card_xls(path).transactions
        plan = plan_job(stored, parsed)
        result.parsed = len(parsed)
        result.keep, result.fix, result.delete = len(plan.keep), len(plan.fix), len(plan.delete)
        result.unmatched_parsed = len(plan.unmatched_parsed)
        by_id = {int(row["id"]): row for row in stored}
        changed_days = [_day(by_id[sid]["ts"]) for sid, _ in plan.fix] + [_day(by_id[sid]["ts"]) for sid, _ in plan.delete]
        result.earliest_change = min(changed_days) if changed_days else None

        if apply and (plan.fix or plan.delete):
            account_id = int(job["account_id"])
            for sid, twin in plan.delete:
                if twin is not None:
                    moved = db.execute(
                        text(
                            """
                            UPDATE category_overrides SET transaction_id = :twin
                            WHERE transaction_id = :sid
                              AND NOT EXISTS (SELECT 1 FROM category_overrides WHERE transaction_id = :twin)
                            """
                        ),
                        {"sid": sid, "twin": twin},
                    ).rowcount
                    result.overrides_moved += int(moved or 0)
                db.execute(text("DELETE FROM transactions WHERE id = :sid"), {"sid": sid})
            for sid, tx in plan.fix:
                # The occurrence among the rows now stored with the corrected key, so the
                # fingerprint matches what a fresh upload of the file would compute (D-35).
                key = _natural_key(tx)
                same = db.execute(
                    text(
                        """
                        SELECT count(*) FROM transactions
                        WHERE account_id = :account AND id <> :sid AND ts = :ts AND type = :type
                          AND amount = :amount AND currency = :currency
                          AND COALESCE(merchant_counterparty, '') = :merchant
                        """
                    ),
                    {"account": account_id, "sid": sid, "ts": key[0], "type": key[1], "amount": key[2],
                     "currency": key[3], "merchant": key[4]},
                ).scalar()
                fp = _free_source_fingerprint(db, account_id, tx, int(same or 0) + 1)
                db.execute(
                    text(
                        """
                        UPDATE transactions
                        SET amount = :amount, type = :type, category = :category,
                            source_fingerprint = :fp, notes = :notes
                        WHERE id = :sid
                        """
                    ),
                    {"amount": tx["amount"], "type": tx["type"], "category": tx.get("category"), "fp": fp,
                     "notes": _compose_notes(fp, tx.get("notes")), "sid": sid},
                )
            mark_rollups_dirty(db, result.earliest_change, account_id=account_id, reason="uob_card_repair")
            db.commit()
        results.append(result)
    return results


def summary_lines(results: List[JobResult], *, applied: bool) -> List[str]:
    lines = []
    for r in results:
        if r.missing_file:
            lines.append(f"job {r.job_id} (account {r.account_id}): raw file missing, skipped ({r.stored} rows)")
            continue
        lines.append(
            f"job {r.job_id} (account {r.account_id}): {r.stored} stored, {r.parsed} in the file: "
            f"keep {r.keep}, correct {r.fix}, delete {r.delete} duplicates"
            + (f", {r.overrides_moved} category overrides moved" if applied else "")
            + (f", {r.unmatched_parsed} file rows not stored (re-upload to add them)" if r.unmatched_parsed else "")
            + (f"; History from {r.earliest_change}" if r.earliest_change else "")
        )
    lines.append("Applied." if applied else "Dry run: nothing changed. APPLY=1 to write.")
    return lines
