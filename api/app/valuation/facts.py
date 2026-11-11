"""Valuation facts: net worth and its components, card liabilities, cash and
cash flow, at an anchor."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Literal, Mapping, overload

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.auth_context import account_scope_sql
from app.crypto.valuation import latest_wallet_valuation
from app.portfolio.canonical_reads import (
    canonical_card_statement_rows,
    canonical_position_rows_by_legacy_account,
    latest_authoritative_nav_by_legacy_account,
)
from app.valuation import clock, fx
from app.valuation.clock import (
    _add_months,
    _card_transaction_in_window,
    _configured_snapshot_day,
    _date_only,
    _is_snapshot_anchor,
    _iso_value,
    _local_date,
    _month_window,
    _normalize_ts,
    _transaction_in_month_window,
    _transaction_query_bounds,
)
from app.valuation.fx import _cashflow_rate_date
from app.valuation.prices import (
    _canonical_base_currency,
    _canonical_position_value,
    _latest_price_map,
    _latest_prices_for_positions,
    _nav_live_context,
    _nav_live_price_deltas,
)
from app.valuation.state import (
    CASH_KIND_STABLECOIN,
    CASH_SCOPE_CASH_PAGE,
    _cash_balance_rows,
    _cash_positions,
    _effective_as_of,
    _wallet_valuation,
)
from app.valuation_cache import valuation_cached
from app.valuation.money import D, ZERO, dsum


_UPPERCASE_SOURCE_CODES = {"DBS", "OCBC", "UOB", "IBKR", "POSB", "CITI", "HSBC", "SCB"}


def _serialize_net_worth(components: Dict[str, Decimal]) -> Dict[str, Decimal]:
    return {
        "total": components["total"],
        "cash": components["cash"],
        "stocks_funds": components["stocks_funds"],
        "crypto": components["crypto"],
        "liabilities": components["liabilities"],
    }


def _card_liability_transaction_start(anchor_ts: datetime) -> date:
    """First day (user's calendar) of the card-spending window ending at
    ``anchor_ts``: the previous month's 1st for a month-end snapshot anchor,
    else the 1st of the anchor's own month (a live "now": its local month)."""
    if _is_snapshot_anchor(anchor_ts):
        anchor_day = anchor_ts.astimezone(timezone.utc).date()
        month_start = date(anchor_day.year, anchor_day.month, 1)
        if anchor_day.day == _configured_snapshot_day():
            previous = month_start - timedelta(days=1)
            return date(previous.year, previous.month, 1)
        return month_start
    local_day = _local_date(anchor_ts)
    return date(local_day.year, local_day.month, 1)


# A card's liability is its running balance (#300, D-76): no age limit on the dated
# balance it starts from (D-52's CARD_STATEMENT_MAX_AGE_DAYS still bounds the read
# layer's default, e.g. account_status's "statement in use" check).


def _card_statements_by_account(
    rows: List[Dict[str, Any]], base_currency: str
) -> Dict[int, tuple[date, list[tuple[str, Decimal]]]]:
    """Per card: (its statement date, [(currency, balance)]) from the rows of
    ``canonical_card_statement_rows`` (each card's newest statement, D-52)."""
    newest_statement: dict[int, date] = {}
    for row in rows:
        as_of = _date_only(row["as_of_date"])
        if as_of is None:
            continue
        account_id = int(row["account_id"])
        if account_id not in newest_statement or as_of > newest_statement[account_id]:
            newest_statement[account_id] = as_of
    statement_balances: dict[int, list[tuple[str, Decimal]]] = {}
    for row in rows:
        account_id = int(row["account_id"])
        if _date_only(row["as_of_date"]) == newest_statement.get(account_id):
            statement_balances.setdefault(account_id, []).append(
                (str(row["currency"] or base_currency).upper(), D(row["balance_local"]))
            )
    return {account_id: (newest_statement[account_id], balances) for account_id, balances in statement_balances.items()}


@valuation_cached()
def _credit_card_liability_details(
    db: Session,
    anchor_ts: datetime,
    base_currency: str,
    current_user_id: int,
) -> list[Dict[str, Any]]:
    """Each of the user's cards at ``anchor_ts``: what it owes, in ``base_currency``.

    Per card (#207, D-76 #300):
    - closed before the anchor's date (``accounts.closed_on``): nothing;
    - else, with a dated balance (``credit_balance`` snapshot: a statement, a
      previous balance, a limit-derived balance) on or before the anchor's date,
      however old: the **running balance**, that balance plus every card
      transaction after its date up to the anchor (charges, fees and interest
      add, payments and refunds subtract). Not clamped: an overpaid card owes
      less than nothing (a credit, ``value`` < 0). A newer balance re-bases it.
    - else its net card transactions in the anchor's card window (the method
      before #207), clamped at 0: with no balance to start from, it's an estimate.
    A newer statement never changes an earlier anchor: only snapshots on or
    before an anchor are read.

    Each entry: account_id, currency (the card's), method (running |
    transactions | closed), as_of_date (the anchoring balance's date, else
    None), value, and for ``running``: anchor_value (the dated balance, owed
    positive) and since_value (the transactions after it), both in base.
    """
    anchor_date = anchor_ts.date()
    cards = db.execute(
        text(
            """
            SELECT
              a.id AS account_id,
              a.currency AS account_currency,
              a.closed_on
            FROM accounts a
            WHERE a.account_type = 'CREDIT_CARD'
              AND """
            + account_scope_sql("a")
        ),
        {"current_user_id": current_user_id},
    ).mappings().all()
    if not cards:
        return []

    statements = _card_statements_by_account(
        canonical_card_statement_rows(db, current_user_id=current_user_id, anchor_date=anchor_date, max_age_days=None),
        base_currency,
    )
    newest_statement = {account_id: as_of for account_id, (as_of, _balances) in statements.items()}
    statement_balances = {account_id: balances for account_id, (_as_of, balances) in statements.items()}

    # The month boundary is midnight in the user's timezone (#202); the query
    # takes a day of slack either side and _card_transaction_in_window decides.
    start_day = _card_liability_transaction_start(anchor_ts)
    earliest = min([start_day, *newest_statement.values()])
    query_start = datetime.combine(earliest - timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    query_end = anchor_ts.astimezone(timezone.utc) + timedelta(days=1)
    transaction_rows = db.execute(
        text(
            """
            SELECT t.account_id, t.amount, t.currency, t.ts
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            WHERE t.ts >= :start
              AND t.ts < :anchor
              AND a.account_type = 'CREDIT_CARD'
              AND t.type IN ('EXPENSE','FEE','TAX','INTEREST','TRANSFER','INCOME')
              AND """
            + account_scope_sql("a")
        ),
        {"start": query_start, "anchor": query_end, "current_user_id": current_user_id},
    ).mappings().all()

    currencies = {str(card["account_currency"] or base_currency).upper() for card in cards}
    currencies.update(str(row["currency"] or base_currency).upper() for row in transaction_rows)
    currencies.update(currency for balances in statement_balances.values() for currency, _ in balances)
    rates = fx.get_rates(anchor_ts, base_currency, currencies)

    def _owed(row: Mapping[str, Any]) -> Decimal:
        currency = str(row["currency"] or base_currency).upper()
        return -D(row["amount"]) * D(rates.get(currency))

    window_outstanding: dict[int, Decimal] = {}
    since_balance: dict[int, Decimal] = {}
    for row in transaction_rows:
        account_id = int(row["account_id"])
        ts = _normalize_ts(row["ts"]) or row["ts"]
        if _card_transaction_in_window(ts, start_day, anchor_ts):
            window_outstanding[account_id] = window_outstanding.get(account_id, ZERO) + _owed(row)
        as_of = newest_statement.get(account_id)
        if as_of is not None and _card_transaction_in_window(ts, as_of + timedelta(days=1), anchor_ts):
            since_balance[account_id] = since_balance.get(account_id, ZERO) + _owed(row)

    # Payments to a card seen only on the paying bank account (#308, D-77): they lower what
    # the running balance says is owed, as a payment in the card's own file would.
    if newest_statement:
        from app.valuation.card_payments import missing_bank_payments

        for payment in missing_bank_payments(db, current_user_id):
            as_of = newest_statement.get(payment.card_account_id)
            day_ts = datetime.combine(payment.day, datetime.min.time(), tzinfo=timezone.utc)
            if as_of is None or not _card_transaction_in_window(day_ts, as_of + timedelta(days=1), anchor_ts):
                continue
            rate = rates.get(payment.currency or base_currency, None)
            if rate is None:
                rate = D(fx.get_rates(anchor_ts, base_currency, {payment.currency}).get(payment.currency))
            since_balance[payment.card_account_id] = since_balance.get(payment.card_account_id, ZERO) - D(payment.amount) * D(rate)

    out: list[Dict[str, Any]] = []
    for card in cards:
        account_id = int(card["account_id"])
        # The card's own currency (#253: currency exposure subtracts what it owes there).
        card_currency = str(card["account_currency"] or base_currency).upper()
        closed_on = _date_only(card["closed_on"])
        if closed_on is not None and closed_on < anchor_date:
            out.append(
                {"account_id": account_id, "currency": card_currency, "method": "closed", "as_of_date": None, "value": ZERO}
            )
            continue
        if account_id in statement_balances:
            # A card's balance is negative while money is owed (the holder's view,
            # like its transactions), so what it owes is minus the balance.
            anchor_value = sum(-amount * D(rates.get(currency)) for currency, amount in statement_balances[account_id])
            since_value = since_balance.get(account_id, ZERO)
            out.append(
                {
                    "account_id": account_id,
                    "currency": card_currency,
                    "method": "running",
                    "as_of_date": newest_statement[account_id],
                    "anchor_value": anchor_value,
                    "since_value": since_value,
                    "value": anchor_value + since_value,
                }
            )
            continue
        out.append(
            {
                "account_id": account_id,
                "currency": card_currency,
                "method": "transactions",
                "as_of_date": None,
                "value": max(window_outstanding.get(account_id, ZERO), ZERO),
            }
        )
    return out


def _credit_card_liability_component(
    db: Session,
    anchor_ts: datetime,
    base_currency: str,
    current_user_id: int,
) -> tuple[Decimal, set[int]]:
    details = _credit_card_liability_details(db, anchor_ts, base_currency, current_user_id)
    return sum(card["value"] for card in details), {int(card["account_id"]) for card in details}


_CASH_FRESHNESS_BALANCE_TYPES = {"cash", "broker_cash", "bank_cash", "stablecoin_cash"}


def _freshness_pair(items: list[tuple[str, Any]]) -> Dict[str, Any]:
    """Most-recent and stalest data point across a set of (label, date) pairs.

    Surfacing both instead of picking one aggregate means neither "your best
    account" nor "your worst account" is hidden from the freshness signal.
    """
    dated: list[tuple[str, str]] = []
    for label, value in items:
        iso = _iso_value(value)
        if iso is not None:
            dated.append((label, iso))
    if not dated:
        return {
            "most_recent_at": None,
            "most_recent_label": None,
            "stalest_at": None,
            "stalest_label": None,
        }
    most_recent_label, most_recent_at = max(dated, key=lambda item: item[1])
    stalest_label, stalest_at = min(dated, key=lambda item: item[1])
    return {
        "most_recent_at": most_recent_at,
        "most_recent_label": most_recent_label,
        "stalest_at": stalest_at,
        "stalest_label": stalest_label,
    }


def _current_networth_state(db: Session, base_currency: str, current_user_id: int) -> Dict[str, Any]:
    anchor = clock._current_anchor_ts()
    components = _networth_components(db, anchor, base_currency, current_user_id, price_overlay=True)
    rows = canonical_position_rows_by_legacy_account(
        db,
        current_user_id=current_user_id,
        anchor_date=anchor.date(),
        include_nav_accounts=True,
    )
    asset_ids = {int(row["asset_id"]) for row in rows if row.get("asset_id") is not None}
    symbol_by_asset = {int(row["asset_id"]): row.get("symbol") for row in rows if row.get("asset_id") is not None}
    live_prices = _latest_price_map(db, anchor, asset_ids)
    stock_items = [
        (symbol_by_asset.get(asset_id) or "Unknown", info.get("trade_date"))
        for asset_id, info in live_prices.items()
    ]

    crypto_valuation = latest_wallet_valuation(db, current_user_id)
    crypto_items = [
        (
            wallet.get("label") or (wallet.get("address") or "")[:10] or wallet.get("chain") or "Wallet",
            wallet.get("as_of_date"),
        )
        for wallet in crypto_valuation.get("wallets", [])
        if wallet.get("as_of_date") is not None
    ]

    cash_items = [
        (_display_source(entry.get("platform")), entry.get("as_of_date"))
        for entry in _cash_positions(db, anchor, base_currency, current_user_id)
        if entry["balance_type"] in _CASH_FRESHNESS_BALANCE_TYPES
    ]

    cash_percent = round((components["cash"] / components["total"]) * 100, 2) if components["total"] > 0 else ZERO
    return {
        "anchor": anchor,
        "net_worth": _serialize_net_worth(components),
        "cash_percent": cash_percent,
        "freshness": {
            "stocks": _freshness_pair(stock_items),
            "crypto": _freshness_pair(crypto_items),
            "cash": _freshness_pair(cash_items),
        },
    }


@valuation_cached(shared=True, date_args=("anchor_ts",))
def _networth_asset_components(
    db: Session,
    anchor_ts: datetime,
    base_currency: str,
    current_user_id: int,
    *,
    price_overlay: bool = False,
) -> Dict[str, Any]:
    """Cash, stocks/funds and crypto at anchor_ts, plus the canonical rows read.

    Everything here depends on anchor_ts only through its date (canonical reads,
    prices and FX are all by date), so it is cached by date (#147). Card
    liabilities depend on the exact anchor time and are added by
    _networth_components.
    """
    canonical_nav_rows = latest_authoritative_nav_by_legacy_account(
        db,
        current_user_id=current_user_id,
        anchor_date=anchor_ts.date(),
    )
    # Canonical position rows for non-NAV accounts (Sharekhan, DBS Vickers)
    canonical_pos_rows = canonical_position_rows_by_legacy_account(
        db,
        current_user_id=current_user_id,
        anchor_date=anchor_ts.date(),
    )
    cash_entries = _cash_positions(db, anchor_ts, base_currency, current_user_id)
    canonical_cash_rows = _cash_balance_rows(
        db,
        current_user_id=current_user_id,
        anchor_date=anchor_ts.date(),
    )
    latest_prices = _latest_prices_for_positions(db, anchor_ts, canonical_pos_rows, enabled=price_overlay)
    nav_live_rows, nav_live_prices, nav_live_currencies = _nav_live_context(
        db, anchor_ts, current_user_id, base_currency, enabled=price_overlay
    )
    currencies = {
        _canonical_base_currency(row, base_currency)
        for row in canonical_pos_rows
    }
    currencies.update(nav_live_currencies)
    currencies.update(str(price["currency"]).upper() for price in latest_prices.values() if price.get("currency"))
    currencies.update(row["base_currency"] for row in canonical_nav_rows if row.get("base_currency"))
    currencies.add("USD")  # Include USD for crypto wallet conversions
    rates = fx.get_rates(anchor_ts, base_currency, currencies)
    cash = sum(D(entry["value"]) for entry in cash_entries)
    stocks_funds = ZERO
    crypto = ZERO
    for r in canonical_pos_rows:
        asset_class = str(r["asset_class"] or "").upper()
        if asset_class in ("STOCK", "FUND"):
            stocks_funds += _canonical_position_value(r, rates, base_currency, latest_prices)
    nav_deltas = _nav_live_price_deltas(nav_live_rows, nav_live_prices, rates, base_currency)
    for row in canonical_nav_rows:
        nav_currency = str(row["base_currency"] or base_currency).upper()
        rate = D(rates.get(nav_currency))
        cash_base = D(row["cash_base"])
        total_nav_base = D(row["total_nav_base"])
        # The NAV's cash is in cash_entries (_cash_positions).
        stocks_funds += (total_nav_base - cash_base) * rate + nav_deltas.get(int(row["legacy_account_id"]), ZERO)
    wallet_usd = D(_wallet_valuation(db, anchor_ts, current_user_id, price_overlay=price_overlay)["total_usd"])
    if wallet_usd:
        usd_rate = D(rates.get("USD"))
        crypto += wallet_usd * usd_rate
    return {
        "cash": cash,
        "stocks_funds": stocks_funds,
        "crypto": crypto,
        "rows": {
            "positions": canonical_pos_rows,
            "nav": canonical_nav_rows,
            "cash": canonical_cash_rows,
        },
    }


@overload
def _networth_components(
    db: Session,
    anchor_ts: datetime,
    base_currency: str,
    current_user_id: int,
    *,
    price_overlay: bool = False,
    return_rows: Literal[False] = False,
) -> Dict[str, Decimal]: ...


@overload
def _networth_components(
    db: Session,
    anchor_ts: datetime,
    base_currency: str,
    current_user_id: int,
    *,
    price_overlay: bool = False,
    return_rows: Literal[True],
) -> tuple[Dict[str, Decimal], Dict[str, Any]]: ...


def _networth_components(
    db: Session,
    anchor_ts: datetime,
    base_currency: str,
    current_user_id: int,
    *,
    price_overlay: bool = False,
    return_rows: bool = False,
) -> Dict[str, Decimal] | tuple[Dict[str, Decimal], Dict[str, Any]]:
    """Compute reporting net worth components from canonical snapshots only.

    When return_rows=True, also returns the raw canonical rows this call fetched
    (positions/nav/cash) so callers building a per-platform freshness breakdown
    (the wealth rollup) don't have to re-issue the same queries.
    """
    if anchor_ts is None:
        empty = {"cash": ZERO, "stocks_funds": ZERO, "crypto": ZERO, "liabilities": ZERO, "total": ZERO}
        if return_rows:
            return empty, {"positions": [], "nav": [], "cash": []}
        return empty
    assets = _networth_asset_components(
        db, anchor_ts, base_currency, current_user_id, price_overlay=price_overlay
    )
    credit_card_liabilities, _card_account_ids = _credit_card_liability_component(
        db,
        anchor_ts,
        base_currency,
        current_user_id,
    )
    cash = assets["cash"]
    stocks_funds = assets["stocks_funds"]
    crypto = assets["crypto"]
    liabilities = credit_card_liabilities
    total = cash + stocks_funds + crypto - liabilities
    result = {
        "cash": cash,
        "stocks_funds": stocks_funds,
        "crypto": crypto,
        "liabilities": liabilities,
        "total": total,
    }
    if return_rows:
        return result, assets["rows"]
    return result


def _sum_balances(items: list[dict[str, Any]]) -> Decimal:
    return dsum(item.get("value") for item in items)


# Below half a cent, a cash row is nothing (#397): wallet dust, a closed account.
_CENT = Decimal("0.005")


def _cash_currency_breakdown(
    current_balances: list[dict[str, Any]],
    snapshot_balances: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Cash by the currency it is held in, now and at the compare point (#397, U12):
    every currency the user holds at either point (no fixed USD/SGD/HKD/INR/Other
    buckets), and none that is zero at both; largest now first."""
    def _by_currency(items: list[dict[str, Any]]) -> dict[str, Decimal]:
        out: dict[str, Decimal] = {}
        for item in items:
            key = str(item.get("currency") or "").upper() or "Other"
            out[key] = out.get(key, ZERO) + D(item.get("value"))
        return out

    current_values = _by_currency(current_balances)
    snapshot_values = _by_currency(snapshot_balances)
    items: list[dict[str, Any]] = []
    for currency in set(current_values) | set(snapshot_values):
        current_value = current_values.get(currency, ZERO)
        snapshot_value = snapshot_values.get(currency, ZERO)
        if abs(current_value) < _CENT and abs(snapshot_value) < _CENT:
            continue
        delta_abs = current_value - snapshot_value
        items.append(
            {
                "currency": currency,
                "current_value": current_value,
                "snapshot_value": snapshot_value,
                "delta_abs": delta_abs,
                "delta_pct": (delta_abs / snapshot_value) if snapshot_value > 0 else None,
            }
        )
    items.sort(key=lambda row: (-row["current_value"], -row["snapshot_value"], row["currency"]))
    return items


@valuation_cached(shared=True, date_args=("anchor_ts",))
def _stablecoin_cash_balances(
    db: Session,
    anchor_ts: datetime,
    base_currency: str,
    current_user_id: int,
) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            WITH latest AS (
              SELECT wallet_id, MAX(as_of_date) AS as_of_date
              FROM crypto_wallet_snapshots
              WHERE as_of_date <= :as_of_date
              GROUP BY wallet_id
            )
            SELECT SUM(i.value_usd) AS total_usd
            FROM crypto_wallet_snapshots s
            JOIN latest l ON l.wallet_id = s.wallet_id AND l.as_of_date = s.as_of_date
            JOIN crypto_wallets w ON w.id = s.wallet_id
            JOIN crypto_wallet_snapshot_items i ON i.snapshot_id = s.id
            WHERE w.status = 'active'
              AND """
            + account_scope_sql("w")
            + """
              AND UPPER(COALESCE(i.symbol, '')) IN ('USDC', 'USDT')
            """
        ),
        {"as_of_date": anchor_ts.date(), "current_user_id": current_user_id},
    ).mappings().all()
    total_usd = sum(D(row.get("total_usd")) for row in rows)
    if total_usd <= 0:
        return []
    usd_rate = D(fx.get_rates(anchor_ts, base_currency, {"USD"}).get("USD"))
    return [{"currency": "USD", "value": total_usd * usd_rate}]


def _stablecoin_usd_by_date(db: Session, anchor_dates: list[date], current_user_id: int) -> Dict[date, Decimal]:
    """USDC/USDT held at each anchor date, in USD: per active wallet, the items
    of its latest snapshot at/before that date (what _stablecoin_cash_balances
    sums for one date), for several dates with two queries instead of one per
    date (#147)."""
    if not anchor_dates:
        return {}
    snapshot_dates = db.execute(
        text(
            """
            SELECT DISTINCT s.wallet_id, s.as_of_date
            FROM crypto_wallet_snapshots s
            JOIN crypto_wallets w ON w.id = s.wallet_id
            WHERE s.as_of_date <= :max_date
              AND w.status = 'active'
              AND """
            + account_scope_sql("w")
        ),
        {"max_date": max(anchor_dates), "current_user_id": current_user_id},
    ).mappings().all()
    dates_by_wallet: Dict[Any, list[date]] = {}
    for row in snapshot_dates:
        as_of = _date_only(row["as_of_date"])
        if as_of is not None:
            dates_by_wallet.setdefault(row["wallet_id"], []).append(as_of)
    # (wallet, snapshot date) used at each anchor date
    used: Dict[date, set[tuple[Any, date]]] = {}
    for anchor_date in anchor_dates:
        used[anchor_date] = set()
        for wallet_id, dates in dates_by_wallet.items():
            eligible = [d for d in dates if d <= anchor_date]
            if eligible:
                used[anchor_date].add((wallet_id, max(eligible)))
    needed = set().union(*used.values())
    if not needed:
        return {anchor_date: ZERO for anchor_date in anchor_dates}
    wallet_ids = sorted({w for w, _ in needed}, key=str)
    wallet_list = ",".join(f":w{i}" for i in range(len(wallet_ids)))
    date_list = sorted({d for _, d in needed})
    params: Dict[str, Any] = {f"w{i}": wallet_id for i, wallet_id in enumerate(wallet_ids)}
    params.update({f"d{i}": d for i, d in enumerate(date_list)})
    rows = db.execute(
        text(
            f"""
            SELECT s.wallet_id, s.as_of_date, SUM(i.value_usd) AS total_usd
            FROM crypto_wallet_snapshots s
            JOIN crypto_wallet_snapshot_items i ON i.snapshot_id = s.id
            WHERE s.wallet_id IN ({wallet_list})
              AND s.as_of_date IN ({",".join(f":d{i}" for i in range(len(date_list)))})
              AND UPPER(COALESCE(i.symbol, '')) IN ('USDC', 'USDT')
            GROUP BY s.wallet_id, s.as_of_date
            """
        ),
        params,
    ).mappings().all()
    by_snapshot = {(row["wallet_id"], _date_only(row["as_of_date"])): row["total_usd"] for row in rows}
    out: Dict[date, Decimal] = {}
    for anchor_date in anchor_dates:
        values = [by_snapshot[pair] for pair in used[anchor_date] if by_snapshot.get(pair) is not None]
        # Postgres returns exact NUMERIC sums: add them exactly, as one SQL SUM would.
        if values and all(isinstance(v, Decimal) for v in values):
            out[anchor_date] = D(sum(values, Decimal(0)))
        else:
            out[anchor_date] = dsum(values)
    return out


def _cash_trend(
    db: Session,
    month_start: datetime,
    base_currency: str,
    current_user_id: int,
) -> list[dict[str, Any]]:
    """The Cash page's cash (net-worth cash plus stablecoins) per month (#241,
    D-61): a month-end for each completed month, the open month live (month to
    date, the Cash headline), and no value for a month whose month-end hasn't
    passed."""
    months = _month_window(month_start, months=6)
    anchors = [clock._trend_point_anchor(candidate_month) for candidate_month in months]
    month_end_dates = [anchor.date() for anchor, is_live in anchors if anchor is not None and not is_live]
    stablecoin_usd = _stablecoin_usd_by_date(db, month_end_dates, current_user_id)
    points: list[dict[str, Any]] = []
    for candidate_month, (anchor, is_live) in zip(months, anchors):
        as_of = _effective_as_of(db, anchor, current_user_id) if anchor is not None else None
        value = None
        if anchor is not None and as_of is not None:
            stablecoin: list[dict[str, Any]] = []
            if is_live:
                # The same figures as the live headline (pages.cash_deposits).
                stablecoin = _stablecoin_cash_balances(db, anchor, base_currency, current_user_id)
            else:
                total_usd = stablecoin_usd.get(anchor.date(), ZERO)
                if total_usd > 0:
                    usd_rate = D(fx.get_rates(anchor, base_currency, {"USD"}).get("USD"))
                    stablecoin = [{"currency": "USD", "value": total_usd * usd_rate}]
            value = _sum_balances(_cash_balances(db, anchor, base_currency, current_user_id) + stablecoin)
        points.append({"month": candidate_month.strftime("%Y-%m"), "value": value, "is_live": is_live})
    return points


def _cash_balances(db: Session, anchor_ts: datetime, base_currency: str, current_user_id: int) -> List[Dict[str, Any]]:
    """Net-worth cash by the currency it is held in (_cash_positions)."""
    buckets: Dict[str, Decimal] = {}
    for entry in _cash_positions(db, anchor_ts, base_currency, current_user_id):
        buckets[entry["currency"]] = buckets.get(entry["currency"], ZERO) + D(entry["value"])
    return [
        {"currency": currency, "value": value}
        for currency, value in sorted(buckets.items(), key=lambda x: x[1], reverse=True)
    ]

def _display_source(value: str | None) -> str:
    if not value:
        return "UNKNOWN"
    text = value.strip()
    if not text:
        return "UNKNOWN"
    upper_text = text.upper()
    if upper_text in _UPPERCASE_SOURCE_CODES or (text.isupper() and len(text) <= 4):
        return upper_text
    return text.lower().title()


def _cash_deposits(db: Session, anchor_ts: datetime, base_currency: str, current_user_id: int) -> Dict[str, Any]:
    """The Cash page's "where cash sits": net-worth cash plus stablecoins
    (_cash_positions, Cash-page scope) by platform, stablecoins by chain."""
    buckets: Dict[str, Decimal] = {}
    for entry in _cash_positions(db, anchor_ts, base_currency, current_user_id, scope=CASH_SCOPE_CASH_PAGE):
        source = _display_source(entry.get("platform"))
        buckets[source] = buckets.get(source, ZERO) + D(entry["value"])

    total = sum(buckets.values())
    items = []
    for source, value in sorted(buckets.items(), key=lambda item: item[1], reverse=True):
        items.append(
            {
                "source": source,
                "value": value,
                "percent": round((value / total) * 100, 2) if total > 0 else ZERO,
            }
        )
    return {"items": items, "total": total}


def _cash_account_rows(
    db: Session,
    current_anchor: datetime,
    compare_anchor: datetime,
    base_currency: str,
    current_user_id: int,
) -> list[dict[str, Any]]:
    """The Cash page's per-account table (#397, U13): each cash account (and each
    stablecoin source) with its balance now and at the compare point, the change,
    and the date of its newest data at the current point. The same cash as the page
    total (Cash-page scope, stablecoins included), so the rows add up to it."""
    def _key(entry: dict[str, Any]) -> tuple[str, str]:
        if entry.get("account_id") is not None:
            return ("account", str(entry["account_id"]))
        return ("source", str(entry.get("platform") or "UNKNOWN"))

    current: dict[tuple[str, str], dict[str, Any]] = {}
    compare: dict[tuple[str, str], Decimal] = {}
    for entry in _cash_positions(db, current_anchor, base_currency, current_user_id, scope=CASH_SCOPE_CASH_PAGE):
        row = current.setdefault(
            _key(entry),
            {"entry": entry, "value": ZERO, "last": None, "currencies": set()},
        )
        row["value"] += D(entry["value"])
        row["currencies"].add(str(entry.get("currency") or base_currency).upper())
        day = _date_only(entry.get("as_of_date"))
        if day is not None and (row["last"] is None or day > row["last"]):
            row["last"] = day
    first_seen: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in _cash_positions(db, compare_anchor, base_currency, current_user_id, scope=CASH_SCOPE_CASH_PAGE):
        key = _key(entry)
        compare[key] = compare.get(key, ZERO) + D(entry["value"])
        first_seen.setdefault(key, entry)

    account_ids = sorted(int(k[1]) for k in set(current) | set(compare) if k[0] == "account")
    names: dict[int, str] = {}
    if account_ids:
        for row in db.execute(
            text("SELECT id, name FROM accounts WHERE id IN :ids").bindparams(bindparam("ids", expanding=True)),
            {"ids": account_ids},
        ).mappings():
            names[int(row["id"])] = str(row["name"] or "")

    rows: list[dict[str, Any]] = []
    for key in set(current) | set(compare):
        now = current.get(key)
        entry = now["entry"] if now else first_seen[key]
        value = now["value"] if now else ZERO
        before = compare.get(key, ZERO)
        # Nothing (to the cent) now or then: dust in a wallet isn't an account row.
        if abs(value) < _CENT and abs(before) < _CENT:
            continue
        platform = _display_source(entry.get("platform"))
        if key[0] == "account":
            label = names.get(int(key[1])) or platform
        else:
            label = f"Stablecoins · {platform}"
        rows.append(
            {
                "account_id": int(key[1]) if key[0] == "account" else None,
                "kind": "stablecoin" if entry.get("kind") == CASH_KIND_STABLECOIN else "account",
                "label": label,
                "platform": platform,
                "currencies": sorted(now["currencies"]) if now else [],
                "current_value": value,
                "snapshot_value": before,
                "delta_abs": value - before,
                "last_data_date": _iso_value(now["last"]) if now and now["last"] else None,
            }
        )
    rows.sort(key=lambda r: (-r["current_value"], r["label"]))
    return rows


@valuation_cached(shared=True)
def _cashflow(db: Session, start: datetime, end: datetime, base_currency: str, current_user_id: int) -> Dict[str, Any]:
    q = text(
        """
        SELECT
          t.ts,
          t.type,
          t.amount,
          t.currency
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        WHERE t.ts >= :start AND t.ts < :end
          AND """
        + account_scope_sql("a")
        + """
        """
    )
    # The month runs midnight to midnight in the user's timezone (#211, D-49).
    query_start, query_end = _transaction_query_bounds(start, end)
    rows = [
        r
        for r in db.execute(
            q, {"start": query_start, "end": query_end, "current_user_id": current_user_id}
        ).mappings().all()
        if _transaction_in_month_window(r["ts"], start, end)
    ]
    # Each flow converts at the rate of its own date (D-30, #170), one store read
    # for the month; a missing rate leaves the row out (never 1.0) and is noted
    # for the response's fx_status (and keeps this result out of the shared cache).
    currencies = {(r["currency"] or base_currency).upper() for r in rows}
    row_dates = [_cashflow_rate_date(r["ts"]) for r in rows]
    rates_by_date: Mapping[date, Mapping[str, Decimal]] = (
        fx.get_rates_by_date(row_dates, base_currency, currencies) if rows else {}
    )
    income = ZERO
    expenses = ZERO
    for r, day in zip(rows, row_dates):
        cur = (r["currency"] or base_currency).upper()
        amount = D(r["amount"]) * D(rates_by_date.get(day, {}).get(cur))
        if r["type"] == "INCOME":
            income += amount
        elif r["type"] in ("EXPENSE", "FEE", "TAX", "INTEREST"):
            expenses += -amount
    net = income - expenses
    savings_rate = (net / income) if income > 0 else None
    return {"income": income, "expenses": expenses, "net": net, "savings_rate": savings_rate}


