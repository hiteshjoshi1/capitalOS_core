from __future__ import annotations

import os
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import CurrentUser, account_scope_sql, require_current_user
from app.db.session import get_db
from app.portfolio.ibkr_flex import (
    IbkrFlexConfigError,
    IbkrFlexError,
    IbkrFlexImportError,
    IbkrFlexImportInProgress,
    run_ibkr_flex_import_from_config,
)

router = APIRouter(prefix="/portfolio", tags=["portfolio"], dependencies=[Depends(require_current_user)])


def _configured_admin_key() -> str | None:
    return os.getenv("IBKR_FLEX_ADMIN_KEY") or os.getenv("STOCK_ADMIN_KEY") or os.getenv("CRYPTO_ADMIN_KEY")


def _validate_admin_key(x_admin_key: str | None) -> None:
    expected = _configured_admin_key()
    if expected and x_admin_key != expected:
        raise HTTPException(status_code=403, detail="Invalid admin key")


def _parse_cutover_date(raw: str | None) -> date:
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid cutover_date. Use YYYY-MM-DD") from exc
    env_value = os.getenv("IBKR_FLEX_CUTOVER_DATE")
    if env_value:
        try:
            return date.fromisoformat(env_value)
        except ValueError as exc:
            raise HTTPException(status_code=500, detail="Invalid IBKR_FLEX_CUTOVER_DATE") from exc
    return date.today()


def _require_ibkr_account(db: Session, account_id: int, current_user_id: int) -> None:
    row = db.execute(
        text(
            """
            SELECT COALESCE(NULLIF(TRIM(a.platform), ''), p.code) AS platform
            FROM accounts AS a
            LEFT JOIN platforms AS p ON p.id = a.platform_id
            WHERE a.id = :account_id
              AND """
            + account_scope_sql("a")
            + """
            """
        ),
        {"account_id": account_id, "current_user_id": current_user_id},
    ).mappings().one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Account not found")
    if str(row["platform"] or "").upper() != "IBKR":
        raise HTTPException(status_code=400, detail="IBKR Flex import requires an IBKR account")


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    iso = getattr(value, "isoformat", None)
    return iso() if callable(iso) else str(value)


@router.post("/ibkr-flex/import-now")
def import_ibkr_flex_now(
    account_id: int = Query(...),
    cutover_date: str | None = Query(None, description="YYYY-MM-DD. Defaults to IBKR_FLEX_CUTOVER_DATE or today."),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
):
    _validate_admin_key(x_admin_key)
    _require_ibkr_account(db, account_id, current_user.id)
    try:
        return run_ibkr_flex_import_from_config(
            db,
            current_user_id=current_user.id,
            legacy_account_id=account_id,
            cutover_date=_parse_cutover_date(cutover_date),
        )
    except IbkrFlexImportInProgress as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IbkrFlexConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except IbkrFlexImportError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message}) from exc
    except IbkrFlexError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/ibkr-flex/import-runs")
def list_ibkr_flex_import_runs(
    account_id: int | None = Query(None),
    limit: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    account_filter = "AND ba.legacy_account_id = :account_id" if account_id is not None else ""
    rows = db.execute(
        text(
            f"""
            SELECT
              r.id,
              r.status,
              r.legacy_account_id,
              r.report_date_from,
              r.report_date_to,
              r.requested_at,
              r.started_at,
              r.finished_at,
              r.error_code,
              r.error_message
            FROM broker_import_runs r
            JOIN broker_accounts ba ON ba.id = r.broker_account_id
            JOIN accounts acc ON acc.id = ba.legacy_account_id
            WHERE r.platform_code = 'IBKR'
              AND r.source_type = 'ibkr_flex_daily'
              AND {account_scope_sql("acc")}
              {account_filter}
            ORDER BY r.requested_at DESC, r.id DESC
            LIMIT :limit
            """
        ),
        {"current_user_id": current_user.id, "account_id": account_id, "limit": limit},
    ).mappings().all()
    return [
        {
            "id": int(row["id"]),
            "status": row["status"],
            "legacy_account_id": int(row["legacy_account_id"]) if row["legacy_account_id"] is not None else None,
            "report_date_from": _iso(row["report_date_from"]),
            "report_date_to": _iso(row["report_date_to"]),
            "requested_at": _iso(row["requested_at"]),
            "started_at": _iso(row["started_at"]),
            "finished_at": _iso(row["finished_at"]),
            "error_code": row["error_code"],
            "error_message": row["error_message"],
        }
        for row in rows
    ]


@router.get("/ibkr-flex/reconciliations")
def list_ibkr_flex_reconciliations(
    account_id: int | None = Query(None),
    limit: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    account_filter = "AND ba.legacy_account_id = :account_id" if account_id is not None else ""
    rows = db.execute(
        text(
            f"""
            SELECT
              rec.id,
              ba.legacy_account_id,
              rec.import_run_id,
              rec.report_date,
              rec.reconciliation_type,
              rec.expected_amount,
              rec.actual_amount,
              rec.difference_amount,
              rec.tolerance_amount,
              rec.status
            FROM portfolio_reconciliations rec
            JOIN broker_accounts ba ON ba.id = rec.broker_account_id
            JOIN accounts acc ON acc.id = ba.legacy_account_id
            WHERE {account_scope_sql("acc")}
              {account_filter}
            ORDER BY rec.report_date DESC, rec.id DESC
            LIMIT :limit
            """
        ),
        {"current_user_id": current_user.id, "account_id": account_id, "limit": limit},
    ).mappings().all()
    return [
        {
            "id": int(row["id"]),
            "legacy_account_id": int(row["legacy_account_id"]) if row["legacy_account_id"] is not None else None,
            "import_run_id": int(row["import_run_id"]),
            "report_date": _iso(row["report_date"]),
            "reconciliation_type": row["reconciliation_type"],
            "expected_amount": float(row["expected_amount"]),
            "actual_amount": float(row["actual_amount"]),
            "difference_amount": float(row["difference_amount"]),
            "tolerance_amount": float(row["tolerance_amount"]),
            "status": row["status"],
        }
        for row in rows
    ]


@router.get("/ibkr-flex/data-quality-events")
def list_ibkr_flex_data_quality_events(
    account_id: int | None = Query(None),
    limit: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    account_filter = "AND ba.legacy_account_id = :account_id" if account_id is not None else ""
    rows = db.execute(
        text(
            f"""
            SELECT
              ev.id,
              ba.legacy_account_id,
              ev.import_run_id,
              ev.report_date,
              ev.severity,
              ev.event_code,
              ev.message,
              ev.created_at
            FROM portfolio_data_quality_events ev
            JOIN broker_accounts ba ON ba.id = ev.broker_account_id
            JOIN accounts acc ON acc.id = ba.legacy_account_id
            WHERE {account_scope_sql("acc")}
              {account_filter}
            ORDER BY ev.created_at DESC, ev.id DESC
            LIMIT :limit
            """
        ),
        {"current_user_id": current_user.id, "account_id": account_id, "limit": limit},
    ).mappings().all()
    return [
        {
            "id": int(row["id"]),
            "legacy_account_id": int(row["legacy_account_id"]) if row["legacy_account_id"] is not None else None,
            "import_run_id": int(row["import_run_id"]) if row["import_run_id"] is not None else None,
            "report_date": _iso(row["report_date"]),
            "severity": row["severity"],
            "event_code": row["event_code"],
            "message": row["message"],
            "created_at": _iso(row["created_at"]),
        }
        for row in rows
    ]
