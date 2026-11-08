"""Fill IBKR's own realised P&L and FX rate into trades stored before #293.

Trades imported before #293 kept neither ``fifoPnlRealized`` nor ``fxRateToBase``. This re-reads
every kept Flex XML (raw_broker_documents) and, for each fill with an execution id, merges those
two values into the stored trade's ``metadata_json`` (same broker account and execution id). A
later report wins for the same fill. Dry run unless apply; prints counts only.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.portfolio.ibkr_flex import parse_flex_statement, trade_metadata


@dataclass
class BackfillResult:
    documents: int = 0
    unreadable: int = 0
    fills_with_values: int = 0
    trades_updated: int = 0
    trades_already_set: int = 0
    trades_not_stored: int = 0


def _meta(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        return json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}


def backfill_realised(db: Session, *, apply: bool) -> BackfillResult:
    result = BackfillResult()
    wanted: Dict[Tuple[int, str], Dict[str, str]] = {}
    docs = db.execute(
        text("SELECT broker_account_id, storage_path FROM raw_broker_documents ORDER BY created_at, id")
    ).mappings().all()
    for doc in docs:
        result.documents += 1
        path = str(doc["storage_path"] or "")
        if not path or not os.path.exists(path):
            result.unreadable += 1
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                statement = parse_flex_statement(handle.read())
        except Exception:  # noqa: BLE001 - one bad file mustn't stop the rest
            result.unreadable += 1
            continue
        for trade in statement.trades:
            values = trade_metadata(trade)
            if trade.broker_execution_id and values:
                wanted[(int(doc["broker_account_id"]), trade.broker_execution_id)] = values
    result.fills_with_values = len(wanted)

    postgres = bool(db.bind and db.bind.dialect.name == "postgresql")
    for (account_id, execution_id), values in wanted.items():
        row = db.execute(
            text(
                """
                SELECT id, metadata_json FROM portfolio_trades
                WHERE broker_account_id = :account AND broker_execution_id = :execution
                """
            ),
            {"account": account_id, "execution": execution_id},
        ).mappings().first()
        if row is None:
            result.trades_not_stored += 1
            continue
        meta = _meta(row["metadata_json"])
        merged = {**meta, **values}
        if merged == meta:
            result.trades_already_set += 1
            continue
        result.trades_updated += 1
        if apply:
            cast = "CAST(:meta AS jsonb)" if postgres else ":meta"
            db.execute(
                text(f"UPDATE portfolio_trades SET metadata_json = {cast} WHERE id = :id"),
                {"meta": json.dumps(merged, sort_keys=True), "id": int(row["id"])},
            )
    if apply:
        db.commit()
    return result


def summary_lines(result: BackfillResult, *, applied: bool) -> list[str]:
    return [
        f"Flex reports read: {result.documents} ({result.unreadable} missing or unreadable)",
        f"Fills with IBKR realised P&L or FX rate: {result.fills_with_values}",
        f"Trades {'updated' if applied else 'to update'}: {result.trades_updated}; already set: "
        f"{result.trades_already_set}; not stored: {result.trades_not_stored}",
        "Applied." if applied else "Dry run: nothing changed. APPLY=1 to write.",
    ]
