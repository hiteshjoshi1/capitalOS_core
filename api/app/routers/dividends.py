from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import CurrentUser, account_scope_sql, require_current_user
from app.db.session import get_db
from app.fx import get_rates
from app.market_data.service import YAHOO_SUFFIX
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
    return [dict(r) for r in db.execute(q, params).mappings().all()]


def _latest_asset_market_values(
    db: Session,
    anchor_ts: datetime,
    base_currency: str,
    current_user_id: int,
) -> dict[int, float]:
    q = text(
        """
        WITH latest AS (
          SELECT p.account_id, MAX(p.as_of) AS as_of
          FROM positions p
          JOIN accounts acc ON acc.id = p.account_id
          WHERE p.as_of <= :anchor_ts
            AND """
            + account_scope_sql("acc")
            + """
          GROUP BY p.account_id
        ),
        latest_prices AS (
          SELECT p1.asset_id, p1.price, p1.currency
          FROM prices p1
          JOIN (
            SELECT asset_id, MAX(trade_date) AS trade_date
            FROM prices
            WHERE trade_date IS NOT NULL AND trade_date <= :anchor_date
            GROUP BY asset_id
          ) lp ON lp.asset_id = p1.asset_id AND lp.trade_date = p1.trade_date
        )
        SELECT
          p.asset_id,
          COALESCE(lp.currency, a.quote_currency) AS quote_currency,
          SUM(
            CASE
              WHEN a.asset_class IN ('STOCK', 'FUND') AND p.quantity IS NOT NULL AND lp.price IS NOT NULL
                THEN p.quantity * lp.price
              ELSE p.cost_basis_base
            END
          ) AS value
        FROM positions p
        JOIN latest l ON l.account_id = p.account_id AND l.as_of = p.as_of
        JOIN assets a ON a.id = p.asset_id
        LEFT JOIN latest_prices lp ON lp.asset_id = p.asset_id
        WHERE a.asset_class IN ('STOCK', 'FUND')
        GROUP BY p.asset_id, COALESCE(lp.currency, a.quote_currency)
        """
    )
    rows = db.execute(
        q,
        {"anchor_ts": anchor_ts, "anchor_date": anchor_ts.date(), "current_user_id": current_user_id},
    ).mappings().all()
    if not rows:
        return {}
    currencies = {(r.get("quote_currency") or base_currency).upper() for r in rows}
    fx_rates = get_rates(anchor_ts, base_currency, currencies)
    out: dict[int, float] = {}
    for row in rows:
        asset = int(row["asset_id"])
        quote_currency = (row.get("quote_currency") or base_currency).upper()
        converted = float(row.get("value") or 0.0) * fx_rates.get(quote_currency, 1.0)
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

    currencies = {(r.get("currency") or base_currency).upper() for r in rows}
    fx_rates = get_rates(anchor_ts, base_currency, currencies)
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
        amount_base = float(row.get("amount") or 0.0) * fx_rates.get(currency, 1.0)
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
    q = text(
        """
        WITH latest AS (
          SELECT p.account_id, MAX(p.as_of) AS as_of
          FROM positions p
          JOIN accounts acc ON acc.id = p.account_id
          WHERE p.as_of <= :anchor_ts
            AND """
            + account_scope_sql("acc")
            + """
          GROUP BY p.account_id
        ),
        latest_holdings AS (
          SELECT p.asset_id, SUM(COALESCE(p.quantity, 0)) AS quantity
          FROM positions p
          JOIN latest l ON l.account_id = p.account_id AND l.as_of = p.as_of
          GROUP BY p.asset_id
        ),
        symbol_pick AS (
          SELECT
            m.asset_id,
            MIN(m.exchange_code) AS exchange_code,
            MIN(m.exchange_symbol) AS exchange_symbol,
            MIN(m.yahoo_symbol_override) AS yahoo_symbol_override
          FROM market_symbol_map m
          WHERE COALESCE(m.is_active, TRUE) = TRUE
          GROUP BY m.asset_id
        )
        SELECT
          a.id AS asset_id,
          a.symbol,
          a.name,
          a.quote_currency,
          a.home_country,
          h.quantity,
          sp.exchange_code,
          sp.exchange_symbol,
          sp.yahoo_symbol_override
        FROM latest_holdings h
        JOIN assets a ON a.id = h.asset_id
        LEFT JOIN symbol_pick sp ON sp.asset_id = a.id
        WHERE a.asset_class IN ('STOCK', 'FUND')
          AND h.quantity > 0
        ORDER BY h.quantity DESC, a.id ASC
        """
    )
    rows = db.execute(q, {"anchor_ts": anchor_ts, "current_user_id": current_user_id}).mappings().all()
    out: list[dict[str, Any]] = []
    for row in rows:
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


def _quantity_on_date(
    db: Session,
    asset_id: int,
    event_date: date,
    snapshot_fallback: float,
    current_user_id: int,
) -> float:
    cutoff = datetime.combine(event_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    trades = db.execute(
        text(
            """
            SELECT type, quantity
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            WHERE t.asset_id = :asset_id
              AND t.ts < :cutoff
              AND t.type IN ('BUY', 'SELL')
              AND t.quantity IS NOT NULL
              AND """
            + account_scope_sql("a")
            + """
            ORDER BY t.ts ASC, t.id ASC
            """
        ),
        {"asset_id": asset_id, "cutoff": cutoff, "current_user_id": current_user_id},
    ).mappings().all()
    if trades:
        qty = 0.0
        for row in trades:
            signed = abs(float(row.get("quantity") or 0.0))
            if str(row.get("type") or "").upper() == "SELL":
                qty -= signed
            else:
                qty += signed
        return max(qty, 0.0)

    snap_row = db.execute(
        text(
            """
            WITH latest AS (
              SELECT p.account_id, MAX(p.as_of) AS as_of
              FROM positions p
              JOIN accounts a ON a.id = p.account_id
              WHERE p.asset_id = :asset_id
                AND p.as_of < :cutoff
                AND """
            + account_scope_sql("a")
            + """
              GROUP BY p.account_id
            )
            SELECT SUM(COALESCE(p.quantity, 0)) AS quantity
            FROM positions p
            JOIN latest l ON l.account_id = p.account_id AND l.as_of = p.as_of
            WHERE p.asset_id = :asset_id
            """
        ),
        {"asset_id": asset_id, "cutoff": cutoff, "current_user_id": current_user_id},
    ).mappings().one_or_none()
    snap_qty = float(snap_row.get("quantity") or 0.0) if snap_row else 0.0
    if snap_qty > 0:
        return snap_qty
    return max(snapshot_fallback, 0.0)


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


def _latest_price_for_asset(db: Session, asset_id: int, anchor_date: date) -> tuple[float | None, str | None]:
    row = db.execute(
        text(
            """
            SELECT price, currency
            FROM prices
            WHERE asset_id = :asset_id
              AND (
                (trade_date IS NOT NULL AND trade_date <= :anchor_date)
                OR trade_date IS NULL
              )
            ORDER BY
              CASE WHEN trade_date IS NULL THEN 1 ELSE 0 END,
              trade_date DESC NULLS LAST,
              ts DESC
            LIMIT 1
            """
        ),
        {"asset_id": asset_id, "anchor_date": anchor_date},
    ).mappings().one_or_none()
    if not row:
        return None, None
    return float(row.get("price") or 0.0), (row.get("currency") or "").upper() or None


def _latest_dividend_snapshot_for_asset(db: Session, asset_id: int, anchor_date: date) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            SELECT yield_rate, annual_dividend_per_share, price, currency, as_of_date
            FROM market_dividend_yields
            WHERE asset_id = :asset_id
              AND as_of_date <= :anchor_date
              AND source <> 'DUMMY'
            ORDER BY as_of_date DESC, updated_at DESC
            LIMIT 1
            """
        ),
        {"asset_id": asset_id, "anchor_date": anchor_date},
    ).mappings().one_or_none()
    if not row:
        return None
    return {
        "yield_rate": float(row.get("yield_rate") or 0.0),
        "annual_dividend_per_share": float(row.get("annual_dividend_per_share") or 0.0),
        "price": float(row.get("price") or 0.0),
        "currency": (row.get("currency") or "").upper() or None,
        "as_of_date": row.get("as_of_date"),
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
    for holding in holdings:
        shares = _quantity_on_date(
            db,
            int(holding["asset_id"]),
            end_date_inclusive,
            float(holding.get("snapshot_quantity") or 0.0),
            current_user.id,
        )
        if shares <= 0:
            continue

        snapshot = _latest_dividend_snapshot_for_asset(db, int(holding["asset_id"]), end_date_inclusive)
        yield_rate = float(snapshot.get("yield_rate") or 0.0) if snapshot else 0.0
        cached_price = float(snapshot.get("price") or 0.0) if snapshot else 0.0
        cached_currency = (snapshot.get("currency") or "").upper() if snapshot else ""

        fallback_price, fallback_currency = _latest_price_for_asset(db, int(holding["asset_id"]), end_date_inclusive)
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
        annual_gross_base = float(row["annual_gross_quote"]) * fx_rates.get(currency, 1.0)
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
