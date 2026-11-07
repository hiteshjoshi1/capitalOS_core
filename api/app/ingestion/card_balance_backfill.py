"""Backfill dated card statement balances from stored statements (#207).

Before #207 a card upload kept only the card's current limits
(``credit_card_accounts``, overwritten each time). Migration 078 turned that one
row into a dated ``credit_balance`` snapshot; this re-parses every imported card
statement still on disk and writes the balance each one states, dated by the
statement (``app.ingestion.card_balances``), as its upload would have.

- Per (account, date, currency) the newest import wins, as uploads do.
- Idempotent: a row that already holds the winning balance and import is left
  alone, so a second run changes nothing.
- Dry run unless ``apply``; History is marked dirty per account from the earliest
  date it changed (D-29).
- Removed imports, non-card accounts and statements stating no balance (Citi)
  are skipped. Reports counts and dates, never amounts.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ingestion.card_balances import (
    CARD_BALANCE_PARSERS,
    CARD_BALANCE_TYPE,
    CardStatementBalance,
    card_statement_balances,
    write_card_statement_balance,
)
from app.wealth_rollup_dirty import mark_rollups_dirty


@dataclass
class JobOutcome:
    job_id: int
    account_id: int
    parser_key: str
    action: str  # insert | update | link | unchanged | superseded | missing_file | no_balance | parse_error
    as_of_date: date | None = None


@dataclass
class BackfillResult:
    applied: bool
    jobs: list[JobOutcome] = field(default_factory=list)
    dirty_from: dict[int, date] = field(default_factory=dict)

    def count(self, action: str) -> int:
        return sum(1 for job in self.jobs if job.action == action)


def _parse(parser_key: str, path: str) -> dict[str, Any]:
    from app.ingestion.runner import PARSER_REGISTRY  # the upload's own parsers

    kind, parser_fn = PARSER_REGISTRY[parser_key]
    result = parser_fn(path, ",") if kind == "csv" else parser_fn(path)
    return dict(result.parser_meta or {})


def _existing(db: Session, account_id: int, as_of: date, currency: str) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            SELECT id, import_job_id, balance_local
            FROM account_balance_snapshots
            WHERE account_id = :account_id
              AND as_of_date = :as_of_date
              AND currency = :currency
              AND balance_type = :balance_type
              AND authority_status = 'authoritative'
            """
        ),
        {"account_id": account_id, "as_of_date": as_of, "currency": currency, "balance_type": CARD_BALANCE_TYPE},
    ).mappings().first()
    return dict(row) if row else None


def backfill_card_balances(db: Session, *, apply: bool = False) -> BackfillResult:
    jobs = db.execute(
        text(
            """
            SELECT j.id, j.account_id, j.parser_key, j.stored_path, UPPER(a.currency) AS currency
            FROM import_jobs j
            JOIN accounts a ON a.id = j.account_id
            WHERE j.status = 'IMPORTED'
              AND a.account_type = 'CREDIT_CARD'
            ORDER BY j.id
            """
        )
    ).mappings().all()
    result = BackfillResult(applied=apply)
    # (account, date, currency) -> (job id, statement): the newest import wins.
    winners: dict[tuple[int, date, str], tuple[int, CardStatementBalance, dict[str, Any] | None]] = {}
    # One outcome per (job, balance date); a job without a balance has one with no date.
    # A UOB history export states several dated balances (#300), each its own outcome.
    outcomes: dict[tuple[int, date | None], JobOutcome] = {}
    for job in jobs:
        parser_key = str(job["parser_key"] or "")
        if parser_key not in CARD_BALANCE_PARSERS:
            continue
        job_id, account_id = int(job["id"]), int(job["account_id"])

        def _job_outcome(action: str) -> None:
            outcomes[(job_id, None)] = JobOutcome(job_id=job_id, account_id=account_id, parser_key=parser_key, action=action)

        path = str(job["stored_path"] or "")
        if not path or not os.path.isfile(path):
            _job_outcome("missing_file")
            continue
        try:
            meta = _parse(parser_key, path)
        except Exception:  # a file that no longer parses is reported, not fatal
            _job_outcome("parse_error")
            continue
        statements = card_statement_balances(parser_key, meta)
        if not statements:
            _job_outcome("no_balance")
            continue
        for statement in statements:
            key = (account_id, statement.as_of_date, str(job["currency"] or "SGD"))
            previous = winners.get(key)
            if previous is not None:
                outcomes[(previous[0], statement.as_of_date)].action = "superseded"
            # A file stating one balance keeps its own parser_meta (e.g. DBS's limits).
            winners[key] = (job_id, statement, meta if len(statements) == 1 else None)
            outcomes[(job_id, statement.as_of_date)] = JobOutcome(
                job_id=job_id, account_id=account_id, parser_key=parser_key, action="pending", as_of_date=statement.as_of_date
            )

    for (account_id, as_of, currency), (job_id, statement, own_meta) in winners.items():
        outcome = outcomes[(job_id, as_of)]
        existing = _existing(db, account_id, as_of, currency)
        if existing is None:
            outcome.action = "insert"
        elif round(float(existing["balance_local"]), 2) != round(statement.balance, 2):
            outcome.action = "update"
        elif existing["import_job_id"] is None or int(existing["import_job_id"]) != job_id:
            outcome.action = "link"  # same balance (e.g. migration 078's row): record its import
        else:
            outcome.action = "unchanged"
            continue
        if outcome.action in ("insert", "update"):
            current = result.dirty_from.get(account_id)
            result.dirty_from[account_id] = as_of if current is None or as_of < current else current
        if apply:
            write_card_statement_balance(
                db,
                account_id=account_id,
                import_job_id=job_id,
                parser_key=outcome.parser_key,
                parser_meta=own_meta if own_meta is not None else _one_balance_meta(statement),
                mark_dirty=False,
            )
    result.jobs = sorted(outcomes.values(), key=lambda o: (o.job_id, o.as_of_date or date.min))
    if apply:
        for account_id, from_date in result.dirty_from.items():
            mark_rollups_dirty(db, from_date, account_id=account_id, reason="card_balance_backfill")
        db.commit()
    else:
        db.rollback()
    return result


def _one_balance_meta(statement: CardStatementBalance) -> dict[str, Any]:
    """parser_meta stating just this one dated balance, so the writer writes only it."""
    return {
        "statement_balances": [
            {"as_of_date": statement.as_of_date.isoformat(), "owed": -statement.balance,
             "source": statement.metadata.get("source")}
        ]
    }


def summary_lines(result: BackfillResult) -> list[str]:
    mode = "APPLIED" if result.applied else "DRY RUN (pass --apply / APPLY=1 to write)"
    lines = [f"Card statement balance backfill: {mode}"]
    actions = ("insert", "update", "link", "unchanged", "superseded", "no_balance", "missing_file", "parse_error")
    lines.append("  " + " ".join(f"{a}={result.count(a)}" for a in actions))
    for job in result.jobs:
        lines.append(
            f"  job {job.job_id} account {job.account_id} {job.parser_key}: {job.action}"
            + (f" as_of={job.as_of_date.isoformat()}" if job.as_of_date else "")
        )
    for account_id, from_date in sorted(result.dirty_from.items()):
        lines.append(f"  account {account_id}: History dirty from {from_date.isoformat()}")
    return lines

