from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import CurrentUser, account_scope_sql, require_current_user
from app.db.session import get_db
from app.fx import fx_status, get_rates, get_rates_by_date, rate_date
from app.market_data.service import YAHOO_SUFFIX
from app.portfolio.canonical_reads import canonical_position_rows_by_legacy_account
from app.portfolio.ledger_dividends import fetch_ledger_dividend_rows, ledger_covered_since
from app.schemas.dividends import (
    DividendCompanyItemOut,
    DividendHistoryEventOut,
    DividendHistoryOut,
    DividendsByCompanyOut,
    DividendSummaryBucketOut,
    DividendSummaryOut,
    DividendTotalsOut,
    ExpectedDividendBucketOut,
    ExpectedDividendCompanyOut,
    ExpectedDividendsOverviewOut,
    ExpectedDividendSummaryOut,
)

router = APIRouter(prefix="/dividends", tags=["dividends"], dependencies=[Depends(require_current_user)])


def _parse_month(value: str) -> datetime:
    try:
        return datetime.strptime(value + "-01", "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid month format. Use YYYY-MM, e.g. 2026-02")


def _add_months(dt: datetime, months: int) -> datetime:
    year = dt.year + (dt.month - 1 + months) // 12
    month = (dt.month - 1 + months) % 12 + 1
    return dt.replace(year=year, month=month)


def _month_end(dt: datetime) -> datetime:
    return _add_months(dt, 1)


def _normalize_tax_rate(raw: float) -> float:
    rate = float(raw)
    if rate > 1:
        rate = rate / 100.0
    if rate < 0:
        return 0.0
    if rate > 1:
        return 1.0
    return rate


def _parse_country_tax_rates(raw: str | None) -> dict[str, float]:
    if not raw:
        return {}
    out: dict[str, float] = {}
    for chunk in raw.split(","):
        if ":" not in chunk:
            continue
        code_raw, rate_raw = chunk.split(":", 1)
        code = code_raw.strip().upper()
        if not code:
            continue
        try:
            out[code] = _normalize_tax_rate(float(rate_raw.strip()))
        except ValueError:
            continue
    return out


def _resolve_range(from_month: str | None, to_month: str | None) -> tuple[datetime, datetime, str, str]:
    now = datetime.now(tz=timezone.utc)
    if to_month:
        to_start = _parse_month(to_month)
    else:
        to_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if from_month:
        from_start = _parse_month(from_month)
    else:
        from_start = _add_months(to_start, -11)
    if from_start > to_start:
        raise HTTPException(status_code=400, detail="from_month must be <= to_month")
    end = _month_end(to_start)
    return from_start, end, from_start.strftime("%Y-%m"), to_start.strftime("%Y-%m")


def _bucket_key(ts_value: datetime | str, period: str) -> str:
    if isinstance(ts_value, str):
        try:
            ts_value = datetime.fromisoformat(ts_value)
        except ValueError:
            ts_value = datetime.now(tz=timezone.utc)
    if ts_value.tzinfo is None:
        ts_value = ts_value.replace(tzinfo=timezone.utc)
    if period == "year":
        return f"{ts_value.year}"
    if period == "quarter":
        quarter = ((ts_value.month - 1) // 3) + 1
        return f"{ts_value.year}-Q{quarter}"
    return ts_value.strftime("%Y-%m")


def _looks_like_dividend_income(row: dict[str, Any]) -> bool:
    txn_type = str(row.get("type") or "").upper()
    category = str(row.get("category") or "").lower()
    resolved_code = str(row.get("resolved_category_code") or "").lower()
    if resolved_code == "income_dividends":
        return True
    return txn_type == "INCOME" and "dividend" in category


def _looks_like_withholding(row: dict[str, Any]) -> bool:
    txn_type = str(row.get("type") or "").upper()
    category = str(row.get("category") or "").lower()
    resolved_code = str(row.get("resolved_category_code") or "").lower()
    if resolved_code == "taxes_withholding":
        return True
    return txn_type == "TAX" or "withholding" in category or category == "brokerage::tax"


def _resolved_tax_rate(country: str | None, assumed_tax_rate: float, country_rates: dict[str, float]) -> float:
    if country:
        override = country_rates.get(country.upper())
        if override is not None:
            return override
    return assumed_tax_rate


def _blank_rollup() -> dict[str, float]:
    return {
        "gross": 0.0,
        "withholding": 0.0,
        "net_received": 0.0,
        "estimated_tax": 0.0,
        "payout_minus_tax": 0.0,
    }


def _fetch_dividend_rows(
    db: Session,
    start: datetime,
    end: datetime,
    current_user_id: int,
    *,
    asset_id: int | None = None,
    symbol: str | None = None,
) -> list[dict[str, Any]]:
    filters: list[str] = []
    params: dict[str, Any] = {"start": start, "end": end}
    if asset_id is not None:
        filters.append("t.asset_id = :asset_id")
        params["asset_id"] = asset_id
    if symbol:
        filters.append("UPPER(COALESCE(a.symbol, t.merchant_counterparty, '')) = :symbol")
        params["symbol"] = symbol.strip().upper()
    where_filters = ""
    if filters:
        where_filters = " AND " + " AND ".join(filters)

    q = text(
        f"""
        SELECT
          t.id,
          t.account_id,
          t.ts,
          t.amount,
          t.currency,
          t.type,
          t.category,
          t.asset_id,
          t.merchant_counterparty,
          a.symbol AS asset_symbol,
          a.name AS asset_name,
          COALESCE(a.home_country, acc.country) AS country,
          COALESCE(resolved_ct.code, '') AS resolved_category_code
        FROM transactions t
        JOIN accounts acc ON acc.id = t.account_id
        LEFT JOIN assets a ON a.id = t.asset_id
        LEFT JOIN category_overrides co ON co.transaction_id = t.id
        LEFT JOIN category_taxonomy override_ct ON override_ct.id = co.category_id
        LEFT JOIN (
          SELECT MIN(id) AS id, LOWER(TRIM(name)) AS normalized_name
          FROM category_taxonomy
          GROUP BY LOWER(TRIM(name))
          HAVING COUNT(*) = 1
        ) parser_ct
          ON parser_ct.normalized_name = LOWER(TRIM(COALESCE(t.category, '')))
        LEFT JOIN category_taxonomy resolved_ct
          ON resolved_ct.id = COALESCE(override_ct.id, parser_ct.id)
        WHERE t.ts >= :start
          AND t.ts < :end
          AND """
        + account_scope_sql("acc")
        + f"""
          AND (
            LOWER(COALESCE(resolved_ct.code, '')) IN ('income_dividends', 'taxes_withholding')
            OR LOWER(COALESCE(t.category, '')) LIKE '%dividend%'
            OR LOWER(COALESCE(t.category, '')) LIKE '%withholding%'
            OR LOWER(COALESCE(t.category, '')) = 'brokerage::tax'
          )
          {where_filters}
        ORDER BY t.ts ASC, t.id ASC
        """
    )
    params["current_user_id"] = current_user_id
    transaction_rows = [dict(r) for r in db.execute(q, params).mappings().all()]

    # IBKR Flex dividends live in the broker cash ledger (#113). For an account the
    # ledger covers, its own lines replace `transactions` rows from that date on.
    covered_since = ledger_covered_since(db, current_user_id)
    rows = [row for row in transaction_rows if not _covered_by_ledger(row, covered_since)]
    rows.extend(fetch_ledger_dividend_rows(db, start, end, current_user_id, asset_id=asset_id, symbol=symbol))
    rows.sort(key=lambda row: (_row_ts(row["ts"]), str(row["id"])))
    return rows


def _row_ts(value: datetime | str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _covered_by_ledger(row: dict[str, Any], covered_since: dict[int, date]) -> bool:
    account_id = row.get("account_id")
    if account_id is None or int(account_id) not in covered_since:
        return False
    return _row_ts(row["ts"]).date() >= covered_since[int(account_id)]


def _latest_asset_market_values(
    db: Session,
    anchor_ts: datetime,
    base_currency: str,
    current_user_id: int,
) -> dict[int, float]:
    rows = canonical_position_rows_by_legacy_account(
        db,
        current_user_id=current_user_id,
        anchor_date=anchor_ts.date(),
        include_nav_accounts=True,
    )
    holding_rows = [
        row
        for row in rows
        if row.get("asset_id") is not None and str(row.get("asset_class") or "").upper() in {"STOCK", "FUND"}
    ]
    if not holding_rows:
        return {}
    currencies: set[str] = set()
    price_by_asset: dict[int, tuple[float | None, str | None]] = {}
    latest_prices = _latest_prices_for_assets(db, {int(row["asset_id"]) for row in holding_rows}, anchor_ts.date())
    for row in holding_rows:
        asset_id = int(row["asset_id"])
        fallback_price, fallback_currency = latest_prices.get(asset_id, (None, None))
        price_by_asset[asset_id] = (fallback_price, fallback_currency)
        if fallback_price is not None and fallback_currency:
            currencies.add(fallback_currency.upper())
        else:
            currencies.add(str(row.get("account_base_currency") or row.get("account_currency") or base_currency).upper())
    fx_rates = get_rates(anchor_ts, base_currency, currencies)
    out: dict[int, float] = {}
    for row in holding_rows:
        asset = int(row["asset_id"])
        latest_price, latest_currency = price_by_asset.get(asset, (None, None))
        if latest_price is not None:
            currency = (latest_currency or row.get("quote_currency") or base_currency).upper()
            value = float(row.get("quantity") or 0.0) * float(latest_price)
        else:
            currency = str(row.get("account_base_currency") or row.get("account_currency") or base_currency).upper()
            value = float(row.get("snapshot_market_value_base") or row.get("cost_basis_base") or 0.0)
        converted = value * fx_rates.get(currency, 0.0)
        out[asset] = out.get(asset, 0.0) + converted
    return out


def _aggregate_dividend_data(
    rows: list[dict[str, Any]],
    *,
    period: str,
    base_currency: str,
    assumed_tax_rate: float,
    country_rates: dict[str, float],
    anchor_ts: datetime,
    current_user_id: int,
    db: Session,
) -> tuple[list[DividendSummaryBucketOut], list[dict[str, Any]], DividendTotalsOut]:
    if not rows:
        empty = DividendTotalsOut(**_blank_rollup())
        return [], [], empty

    # FX-date rule (#139): a dividend is a flow, so it converts at the rate of
    # its own payment date, not the end of the range. One store read covers all
    # the dates. A currency with no rate converts to 0 and the response says so.
    currencies = {(r.get("currency") or base_currency).upper() for r in rows}
    rates_by_date = get_rates_by_date([r["ts"] for r in rows], base_currency, currencies)
    bucket_rollups: dict[str, dict[str, float]] = {}
    company_rollups: dict[tuple[int | None, str], dict[str, Any]] = {}

    for row in rows:
        ts_value = row["ts"]
        bucket = _bucket_key(ts_value, period)
        row_rollup = bucket_rollups.setdefault(bucket, _blank_rollup())

        asset_id = int(row["asset_id"]) if row.get("asset_id") is not None else None
        symbol = str(row.get("asset_symbol") or row.get("merchant_counterparty") or "UNKNOWN").strip() or "UNKNOWN"
        company = str(row.get("asset_name") or row.get("asset_symbol") or row.get("merchant_counterparty") or "UNKNOWN").strip() or "UNKNOWN"
        country = row.get("country")
        company_key = (asset_id, company)
        company_rollup = company_rollups.setdefault(
            company_key,
            {
                "asset_id": asset_id,
                "symbol": symbol,
                "company": company,
                "country": country,
                **_blank_rollup(),
            },
        )

        currency = (row.get("currency") or base_currency).upper()
        amount_base = float(row.get("amount") or 0.0) * rates_by_date[rate_date(ts_value)].get(currency, 0.0)
        tax_rate = _resolved_tax_rate(country, assumed_tax_rate, country_rates)

        gross = 0.0
        estimated_tax = 0.0
        if _looks_like_dividend_income(row):
            gross = max(amount_base, 0.0)
            estimated_tax = gross * tax_rate
        withholding = abs(amount_base) if _looks_like_withholding(row) else 0.0
        net_received = amount_base
        payout_minus_tax = net_received - estimated_tax

        for target in (row_rollup, company_rollup):
            target["gross"] += gross
            target["withholding"] += withholding
            target["net_received"] += net_received
            target["estimated_tax"] += estimated_tax
            target["payout_minus_tax"] += payout_minus_tax

    bucket_items = [
        DividendSummaryBucketOut(
            bucket=key,
            gross=values["gross"],
            withholding=values["withholding"],
            net_received=values["net_received"],
            estimated_tax=values["estimated_tax"],
            payout_minus_tax=values["payout_minus_tax"],
        )
        for key, values in sorted(bucket_rollups.items(), key=lambda kv: kv[0])
    ]

    totals = _blank_rollup()
    for item in bucket_items:
        totals["gross"] += item.gross
        totals["withholding"] += item.withholding
        totals["net_received"] += item.net_received
        totals["estimated_tax"] += item.estimated_tax
        totals["payout_minus_tax"] += item.payout_minus_tax

    asset_values = _latest_asset_market_values(db, anchor_ts, base_currency, current_user_id)
    company_items: list[dict[str, Any]] = []
    for item in company_rollups.values():
        asset_id = item["asset_id"]
        yield_pct: float | None = None
        if asset_id is not None:
            denom = asset_values.get(int(asset_id))
            if denom and denom > 0:
                yield_pct = (item["gross"] / denom) * 100.0
        company_items.append(
            {
                "asset_id": asset_id,
                "symbol": item["symbol"],
                "company": item["company"],
                "country": item["country"],
                "gross": item["gross"],
                "withholding": item["withholding"],
                "net_received": item["net_received"],
                "estimated_tax": item["estimated_tax"],
                "payout_minus_tax": item["payout_minus_tax"],
                "yield_pct": yield_pct,
            }
        )
    company_items.sort(key=lambda item: item["gross"], reverse=True)

    return bucket_items, company_items, DividendTotalsOut(**totals)


@router.get("/summary", response_model=DividendSummaryOut)
def dividends_summary(
    from_month: str | None = Query(None, description="Inclusive month lower bound (YYYY-MM)"),
    to_month: str | None = Query(None, description="Inclusive month upper bound (YYYY-MM)"),
    period: str = Query("month", pattern="^(month|quarter|year)$"),
    base_currency: str = Query("SGD"),
    assumed_tax_rate: float = Query(0.0, ge=0.0),
    country_tax_rates: str | None = Query(None, description="Comma-separated rates, e.g. US:0.15,IN:0.10"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    start, end, from_key, to_key = _resolve_range(from_month, to_month)
    normalized_default_rate = _normalize_tax_rate(assumed_tax_rate)
    country_rates = _parse_country_tax_rates(country_tax_rates)
    rows = _fetch_dividend_rows(db, start, end, current_user.id)
    buckets, _company, totals = _aggregate_dividend_data(
        rows,
        period=period,
        base_currency=base_currency,
        assumed_tax_rate=normalized_default_rate,
        country_rates=country_rates,
        anchor_ts=end,
        current_user_id=current_user.id,
        db=db,
    )
    return DividendSummaryOut(
        from_month=from_key,
        to_month=to_key,
        period=period,
        base_currency=base_currency,
        assumed_tax_rate=normalized_default_rate,
        country_tax_rates=country_rates,
        buckets=buckets,
        totals=totals,
        **fx_status(),
    )


@router.get("/by-company", response_model=DividendsByCompanyOut)
def dividends_by_company(
    from_month: str | None = Query(None, description="Inclusive month lower bound (YYYY-MM)"),
    to_month: str | None = Query(None, description="Inclusive month upper bound (YYYY-MM)"),
    base_currency: str = Query("SGD"),
    assumed_tax_rate: float = Query(0.0, ge=0.0),
    country_tax_rates: str | None = Query(None, description="Comma-separated rates, e.g. US:0.15,IN:0.10"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    start, end, from_key, to_key = _resolve_range(from_month, to_month)
    normalized_default_rate = _normalize_tax_rate(assumed_tax_rate)
    country_rates = _parse_country_tax_rates(country_tax_rates)
    rows = _fetch_dividend_rows(db, start, end, current_user.id)
    _buckets, company_rows, totals = _aggregate_dividend_data(
        rows,
        period="month",
        base_currency=base_currency,
        assumed_tax_rate=normalized_default_rate,
        country_rates=country_rates,
        anchor_ts=end,
        current_user_id=current_user.id,
        db=db,
    )
    items = [DividendCompanyItemOut(**row) for row in company_rows]
    return DividendsByCompanyOut(
        from_month=from_key,
        to_month=to_key,
        base_currency=base_currency,
        assumed_tax_rate=normalized_default_rate,
        country_tax_rates=country_rates,
        items=items,
        totals=totals,
        **fx_status(),
    )


@router.get("/history", response_model=DividendHistoryOut)
def dividends_history(
    asset_id: int | None = Query(None),
    symbol: str | None = Query(None),
    from_month: str | None = Query(None, description="Inclusive month lower bound (YYYY-MM)"),
    to_month: str | None = Query(None, description="Inclusive month upper bound (YYYY-MM)"),
    base_currency: str = Query("SGD"),
    assumed_tax_rate: float = Query(0.0, ge=0.0),
    country_tax_rates: str | None = Query(None, description="Comma-separated rates, e.g. US:0.15,IN:0.10"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    if asset_id is None and (symbol is None or not symbol.strip()):
        raise HTTPException(status_code=400, detail="Either asset_id or symbol is required")

    start, end, from_key, to_key = _resolve_range(from_month, to_month)
    normalized_default_rate = _normalize_tax_rate(assumed_tax_rate)
    country_rates = _parse_country_tax_rates(country_tax_rates)
    rows = _fetch_dividend_rows(db, start, end, current_user.id, asset_id=asset_id, symbol=symbol)
    buckets, company_rows, totals = _aggregate_dividend_data(
        rows,
        period="month",
        base_currency=base_currency,
        assumed_tax_rate=normalized_default_rate,
        country_rates=country_rates,
        anchor_ts=end,
        current_user_id=current_user.id,
        db=db,
    )

    selected: dict[str, Any] | None = None
    if company_rows:
        if asset_id is not None:
            selected = next((row for row in company_rows if row.get("asset_id") == asset_id), company_rows[0])
        else:
            symbol_upper = symbol.strip().upper() if symbol else ""
            selected = next((row for row in company_rows if str(row.get("symbol") or "").upper() == symbol_upper), company_rows[0])

    events = [
        DividendHistoryEventOut(
            month=bucket.bucket,
            gross=bucket.gross,
            withholding=bucket.withholding,
            net_received=bucket.net_received,
            estimated_tax=bucket.estimated_tax,
            payout_minus_tax=bucket.payout_minus_tax,
        )
        for bucket in buckets
    ]

    return DividendHistoryOut(
        from_month=from_key,
        to_month=to_key,
        base_currency=base_currency,
        assumed_tax_rate=normalized_default_rate,
        country_tax_rates=country_rates,
        asset_id=selected.get("asset_id") if selected else asset_id,
        symbol=selected.get("symbol") if selected else (symbol.strip().upper() if symbol else None),
        company=selected.get("company") if selected else None,
        yield_pct=selected.get("yield_pct") if selected else None,
        events=events,
        totals=totals,
        **fx_status(),
    )


def _to_yahoo_symbol(symbol: str, exchange_code: str | None) -> str:
    base = (symbol or "").strip().upper()
    if not exchange_code:
        return base
    ex = exchange_code.strip().upper()
    suffix = YAHOO_SUFFIX.get(ex, "")
    out = base
    if suffix and not out.endswith(suffix):
        out = f"{out}{suffix}"
    if ex == "HKEX" and out.endswith(".HK"):
        hk_base = out[:-3]
        if hk_base.isdigit() and len(hk_base) < 4:
            return f"{hk_base.zfill(4)}.HK"
    return out


def _load_expected_holdings(db: Session, anchor_ts: datetime, current_user_id: int) -> list[dict[str, Any]]:
    rows = canonical_position_rows_by_legacy_account(
        db,
        current_user_id=current_user_id,
        anchor_date=anchor_ts.date(),
        include_nav_accounts=True,
    )
    aggregated: dict[int, dict[str, Any]] = {}
    for row in rows:
        if row.get("asset_id") is None or str(row.get("asset_class") or "").upper() not in {"STOCK", "FUND"}:
            continue
        quantity = float(row.get("quantity") or 0.0)
        if quantity <= 0:
            continue
        asset_id = int(row["asset_id"])
        item = aggregated.setdefault(asset_id, dict(row, quantity=0.0))
        item["quantity"] = float(item.get("quantity") or 0.0) + quantity
    out: list[dict[str, Any]] = []
    for row in sorted(aggregated.values(), key=lambda r: (-float(r.get("quantity") or 0.0), int(r["asset_id"]))):
        exchange_code = (row.get("exchange_code") or "").strip().upper() or None
        exchange_symbol = (row.get("exchange_symbol") or row.get("symbol") or "").strip().upper()
        yahoo_override = (row.get("yahoo_symbol_override") or "").strip().upper()
        yahoo_symbol_seed = yahoo_override or exchange_symbol
        yahoo_symbol = _to_yahoo_symbol(yahoo_symbol_seed, exchange_code)
        out.append(
            {
                "asset_id": int(row["asset_id"]),
                "symbol": str(row.get("symbol") or "").strip().upper(),
                "company": str(row.get("name") or row.get("symbol") or "").strip() or str(row.get("symbol") or ""),
                "country": row.get("home_country"),
                "quote_currency": (row.get("quote_currency") or "USD").upper(),
                "exchange_code": exchange_code,
                "yahoo_symbol": yahoo_symbol,
                "snapshot_quantity": float(row.get("quantity") or 0.0),
            }
        )
    return out


def _quantities_on_date(
    db: Session,
    holdings: list[dict[str, Any]],
    event_date: date,
    current_user_id: int,
) -> dict[int, float]:
    """Shares held of each holding's asset on event_date: from BUY/SELL trades
    when the asset has any, else the canonical snapshot quantity at that date,
    else the holding's snapshot_quantity. One trades query and one snapshot read
    for all holdings (#147; it used to be one of each per holding)."""
    asset_ids = sorted({int(h["asset_id"]) for h in holdings})
    if not asset_ids:
        return {}
    cutoff = datetime.combine(event_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    trades = db.execute(
        text(
            f"""
            SELECT t.asset_id, t.type, t.quantity
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            WHERE t.asset_id IN ({_int_list_sql(asset_ids)})
              AND t.ts < :cutoff
              AND t.type IN ('BUY', 'SELL')
              AND t.quantity IS NOT NULL
              AND """
            + account_scope_sql("a")
            + """
            ORDER BY t.asset_id ASC, t.ts ASC, t.id ASC
            """
        ),
        {"cutoff": cutoff, "current_user_id": current_user_id},
    ).mappings().all()
    from_trades: dict[int, float] = {}
    for row in trades:
        asset_id = int(row["asset_id"])
        signed = abs(float(row.get("quantity") or 0.0))
        if str(row.get("type") or "").upper() == "SELL":
            signed = -signed
        from_trades[asset_id] = from_trades.get(asset_id, 0.0) + signed

    snapshot_qty: dict[int, float] | None = None
    out: dict[int, float] = {}
    for holding in holdings:
        asset_id = int(holding["asset_id"])
        if asset_id in from_trades:
            out[asset_id] = max(from_trades[asset_id], 0.0)
            continue
        if snapshot_qty is None:
            snapshot_qty = {}
            for row in canonical_position_rows_by_legacy_account(
                db,
                current_user_id=current_user_id,
                anchor_date=event_date,
                include_nav_accounts=True,
            ):
                if row.get("asset_id") is not None:
                    key = int(row["asset_id"])
                    snapshot_qty[key] = snapshot_qty.get(key, 0.0) + float(row.get("quantity") or 0.0)
        snap_qty = snapshot_qty.get(asset_id, 0.0)
        out[asset_id] = snap_qty if snap_qty > 0 else max(float(holding.get("snapshot_quantity") or 0.0), 0.0)
    return out


def _blank_expected_rollup() -> dict[str, float]:
    return {"gross": 0.0, "estimated_tax": 0.0, "payout_minus_tax": 0.0}


def _expected_summary_from_buckets(period: str, buckets_raw: dict[str, dict[str, float]]) -> ExpectedDividendSummaryOut:
    buckets = [
        ExpectedDividendBucketOut(
            bucket=key,
            gross=vals["gross"],
            estimated_tax=vals["estimated_tax"],
            payout_minus_tax=vals["payout_minus_tax"],
        )
        for key, vals in sorted(buckets_raw.items(), key=lambda kv: kv[0])
    ]
    gross = sum(bucket.gross for bucket in buckets)
    estimated_tax = sum(bucket.estimated_tax for bucket in buckets)
    payout_minus_tax = sum(bucket.payout_minus_tax for bucket in buckets)
    return ExpectedDividendSummaryOut(
        period=period,
        buckets=buckets,
        gross=gross,
        estimated_tax=estimated_tax,
        payout_minus_tax=payout_minus_tax,
    )


def _int_list_sql(ids: Any) -> str:
    """Inline a list of integer ids (ints only, so safe to format into SQL)."""
    return ",".join(str(int(i)) for i in ids)


def _latest_row_per_asset_sql(
    db: Session, asset_ids: list[int], *, table: str, columns: str, where: str, order_by: str
) -> str:
    """One row per asset id: the first `table` row (alias src) matching `where`,
    ordered by `order_by`, the way a per-asset `... ORDER BY ... LIMIT 1` would.

    Postgres runs it as LATERAL ... LIMIT 1 (an index lookup per asset); SQLite
    (tests) has no LATERAL, so it ranks with ROW_NUMBER() over the same ORDER BY.
    """
    if db.get_bind().dialect.name == "postgresql":
        values = ",".join(f"({int(i)})" for i in asset_ids)
        return f"""
            SELECT ids.asset_id, x.*
            FROM (VALUES {values}) AS ids(asset_id)
            CROSS JOIN LATERAL (
              SELECT {columns}
              FROM {table} src
              WHERE src.asset_id = ids.asset_id AND {where}
              ORDER BY {order_by}
              LIMIT 1
            ) x
        """
    return f"""
        SELECT * FROM (
          SELECT src.asset_id AS asset_id, {columns},
                 ROW_NUMBER() OVER (PARTITION BY src.asset_id ORDER BY {order_by}) AS _rn
          FROM {table} src
          WHERE src.asset_id IN ({_int_list_sql(asset_ids)}) AND {where}
        ) ranked
        WHERE _rn = 1
    """


def _latest_prices_for_assets(
    db: Session, asset_ids: set[int], anchor_date: date
) -> dict[int, tuple[float | None, str | None]]:
    """Per asset: the latest price at/before anchor_date (dated rows first,
    then undated, newest ts first), as (price, currency)."""
    ids = sorted(asset_ids)
    if not ids:
        return {}
    sql = _latest_row_per_asset_sql(
        db,
        ids,
        table="prices",
        columns="src.price, src.currency",
        where="((src.trade_date IS NOT NULL AND src.trade_date <= :anchor_date) OR src.trade_date IS NULL)",
        order_by="CASE WHEN src.trade_date IS NULL THEN 1 ELSE 0 END, src.trade_date DESC NULLS LAST, src.ts DESC",
    )
    rows = db.execute(text(sql), {"anchor_date": anchor_date}).mappings().all()
    return {
        int(row["asset_id"]): (float(row.get("price") or 0.0), (row.get("currency") or "").upper() or None)
        for row in rows
    }


def _latest_dividend_snapshots_for_assets(
    db: Session, asset_ids: set[int], anchor_date: date
) -> dict[int, dict[str, Any]]:
    """Per asset: the latest non-demo dividend-yield snapshot at/before anchor_date."""
    ids = sorted(asset_ids)
    if not ids:
        return {}
    sql = _latest_row_per_asset_sql(
        db,
        ids,
        table="market_dividend_yields",
        columns="src.yield_rate, src.annual_dividend_per_share, src.price, src.currency, src.as_of_date",
        where="src.as_of_date <= :anchor_date AND src.source <> 'DUMMY'",
        order_by="src.as_of_date DESC, src.updated_at DESC",
    )
    rows = db.execute(text(sql), {"anchor_date": anchor_date}).mappings().all()
    return {
        int(row["asset_id"]): {
            "yield_rate": float(row.get("yield_rate") or 0.0),
            "annual_dividend_per_share": float(row.get("annual_dividend_per_share") or 0.0),
            "price": float(row.get("price") or 0.0),
            "currency": (row.get("currency") or "").upper() or None,
            "as_of_date": row.get("as_of_date"),
        }
        for row in rows
    }


@router.get("/expected/overview", response_model=ExpectedDividendsOverviewOut)
def expected_dividends_overview(
    from_month: str | None = Query(None, description="Inclusive month lower bound (YYYY-MM)"),
    to_month: str | None = Query(None, description="Inclusive month upper bound (YYYY-MM)"),
    base_currency: str = Query("SGD"),
    assumed_tax_rate: float = Query(0.0, ge=0.0),
    country_tax_rates: str | None = Query(None, description="Comma-separated rates, e.g. US:0.15,IN:0.10"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    start, end, from_key, to_key = _resolve_range(from_month, to_month)
    anchor_month_dt = _parse_month(to_key)
    anchor_month_key = to_key
    anchor_quarter_key = _bucket_key(anchor_month_dt, "quarter")
    anchor_year_key = _bucket_key(anchor_month_dt, "year")
    end_date_inclusive = (end - timedelta(days=1)).date()
    normalized_default_rate = _normalize_tax_rate(assumed_tax_rate)
    country_rates = _parse_country_tax_rates(country_tax_rates)
    holdings = _load_expected_holdings(db, end, current_user.id)
    if not holdings:
        empty = _expected_summary_from_buckets("month", {})
        return ExpectedDividendsOverviewOut(
            from_month=from_key,
            to_month=to_key,
            base_currency=base_currency,
            assumed_tax_rate=normalized_default_rate,
            country_tax_rates=country_rates,
            holdings_considered=0,
            assets_with_actions=0,
            actions_evaluated=0,
            monthly=empty,
            quarterly=_expected_summary_from_buckets("quarter", {}),
            yearly=_expected_summary_from_buckets("year", {}),
            companies=[],
        )

    company_rows: list[dict[str, Any]] = []
    assets_with_actions = 0
    actions_evaluated = 0
    holding_asset_ids = {int(holding["asset_id"]) for holding in holdings}
    shares_by_asset = _quantities_on_date(db, holdings, end_date_inclusive, current_user.id)
    snapshots = _latest_dividend_snapshots_for_assets(db, holding_asset_ids, end_date_inclusive)
    latest_prices = _latest_prices_for_assets(db, holding_asset_ids, end_date_inclusive)
    for holding in holdings:
        shares = shares_by_asset.get(int(holding["asset_id"]), 0.0)
        if shares <= 0:
            continue

        snapshot = snapshots.get(int(holding["asset_id"]))
        yield_rate = float(snapshot.get("yield_rate") or 0.0) if snapshot else 0.0
        cached_price = float(snapshot.get("price") or 0.0) if snapshot else 0.0
        cached_currency = (snapshot.get("currency") or "").upper() if snapshot else ""

        fallback_price, fallback_currency = latest_prices.get(int(holding["asset_id"]), (None, None))
        price_quote = cached_price if cached_price > 0 else (float(fallback_price or 0.0))
        price_currency = cached_currency or (fallback_currency or "")
        currency = (price_currency or holding.get("quote_currency") or base_currency).upper()

        annual_gross_quote = 0.0
        if yield_rate > 0 and price_quote > 0:
            annual_gross_quote = shares * price_quote * yield_rate
            assets_with_actions += 1
        if snapshot is not None:
            actions_evaluated += 1

        if annual_gross_quote > 0:
            company_rows.append(
                {
                    "asset_id": int(holding["asset_id"]),
                    "symbol": str(holding["symbol"]),
                    "company": str(holding["company"]),
                    "country": holding.get("country"),
                    "shares": shares,
                    "yield_rate": yield_rate,
                    "price": price_quote,
                    "quote_currency": currency,
                    "annual_gross_quote": annual_gross_quote,
                }
            )

    currencies = {(row.get("quote_currency") or base_currency).upper() for row in company_rows}
    fx_rates = get_rates(end, base_currency, currencies) if currencies else {}

    annual_rollup = _blank_expected_rollup()
    companies: list[ExpectedDividendCompanyOut] = []
    for row in company_rows:
        currency = (row.get("quote_currency") or base_currency).upper()
        annual_gross_base = float(row["annual_gross_quote"]) * fx_rates.get(currency, 0.0)
        country = row.get("country")
        tax_rate = _resolved_tax_rate(country, normalized_default_rate, country_rates)
        annual_estimated_tax = annual_gross_base * tax_rate
        annual_payout_minus_tax = annual_gross_base - annual_estimated_tax
        quarterly_gross_base = annual_gross_base / 4.0
        monthly_gross_base = annual_gross_base / 12.0

        annual_rollup["gross"] += annual_gross_base
        annual_rollup["estimated_tax"] += annual_estimated_tax
        annual_rollup["payout_minus_tax"] += annual_payout_minus_tax

        companies.append(
            ExpectedDividendCompanyOut(
                asset_id=int(row["asset_id"]),
                symbol=str(row["symbol"]),
                company=str(row["company"]),
                country=row.get("country"),
                shares=float(row["shares"]),
                yield_pct=(float(row["yield_rate"]) * 100.0) if row.get("yield_rate") is not None else None,
                price=float(row["price"]) if row.get("price") is not None else None,
                quote_currency=currency,
                yearly_dividend=annual_gross_base,
                quarterly_dividend=quarterly_gross_base,
                monthly_dividend=monthly_gross_base,
                gross=annual_gross_base,
                estimated_tax=annual_estimated_tax,
                payout_minus_tax=annual_payout_minus_tax,
            )
        )
    companies.sort(key=lambda item: item.gross, reverse=True)

    monthly_selected = {
        anchor_month_key: {
            "gross": annual_rollup["gross"] / 12.0,
            "estimated_tax": annual_rollup["estimated_tax"] / 12.0,
            "payout_minus_tax": annual_rollup["payout_minus_tax"] / 12.0,
        }
    }
    quarterly_selected = {
        anchor_quarter_key: {
            "gross": annual_rollup["gross"] / 4.0,
            "estimated_tax": annual_rollup["estimated_tax"] / 4.0,
            "payout_minus_tax": annual_rollup["payout_minus_tax"] / 4.0,
        }
    }
    yearly_selected = {anchor_year_key: annual_rollup}

    return ExpectedDividendsOverviewOut(
        from_month=from_key,
        to_month=to_key,
        base_currency=base_currency,
        assumed_tax_rate=normalized_default_rate,
        country_tax_rates=country_rates,
        holdings_considered=len(holdings),
        assets_with_actions=assets_with_actions,
        actions_evaluated=actions_evaluated,
        monthly=_expected_summary_from_buckets("month", monthly_selected),
        quarterly=_expected_summary_from_buckets("quarter", quarterly_selected),
        yearly=_expected_summary_from_buckets("year", yearly_selected),
        companies=companies,
    )
