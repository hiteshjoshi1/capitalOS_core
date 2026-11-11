"""Account state at an anchor: the one cash scope (#144, #180), card accounts,
wallets and snapshot coverage, read from the canonical facts."""
from __future__ import annotations

from decimal import Decimal

from datetime import date, datetime
from typing import Any, Dict, List, Mapping, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import account_scope_sql
from app.crypto.valuation import latest_wallet_valuation
from app.portfolio.canonical_reads import (
    canonical_account_balance_rows,
    canonical_snapshot_coverage_as_of,
    latest_authoritative_nav_by_legacy_account,
)
from app.valuation import clock, fx
from app.valuation.clock import _date_only, _iso_value, _normalize_ts
from app.valuation.prices import _canonical_base_currency
from app.valuation_cache import valuation_cached
from app.valuation.money import D, ZERO


def _effective_as_of(db: Session, anchor_ts: datetime, current_user_id: int) -> Optional[datetime]:
    as_of = canonical_snapshot_coverage_as_of(
        db,
        current_user_id=current_user_id,
        anchor_date=anchor_ts.date(),
    )
    return _normalize_ts(as_of)


def _snapshot_freshness(db: Session, anchor_ts: datetime, current_user_id: int) -> tuple[Optional[datetime], bool, str]:
    as_of = _effective_as_of(db, anchor_ts, current_user_id)
    if as_of is None:
        return None, False, "missing"
    exact = as_of.date() == anchor_ts.date()
    return as_of, exact, ("exact" if exact else "synthetic")


def _positions_coverage_as_of(db: Session, anchor_ts: datetime, current_user_id: int) -> Optional[datetime]:
    as_of = canonical_snapshot_coverage_as_of(
        db,
        current_user_id=current_user_id,
        anchor_date=anchor_ts.date(),
        include_cash=False,
    )
    return _normalize_ts(as_of)


@valuation_cached(shared=True)
def _crypto_snapshot_coverage_as_of(db: Session, anchor_date: Any, current_user_id: int) -> Any:
    q = text(
        """
        WITH latest AS (
          SELECT s.wallet_id, MAX(s.as_of_date) AS as_of_date
          FROM crypto_wallet_snapshots s
          JOIN crypto_wallets w ON w.id = s.wallet_id
          WHERE s.as_of_date <= :anchor_date
            AND w.status = 'active'
            AND """
        + account_scope_sql("w")
        + """
          GROUP BY s.wallet_id
        )
        SELECT MIN(as_of_date) AS as_of_date FROM latest
        """
    )
    row = db.execute(q, {"anchor_date": anchor_date, "current_user_id": current_user_id}).mappings().one()
    return row["as_of_date"]


def _cash_row_amount(row: Dict[str, Any], fallback_currency: str) -> tuple[Decimal, str]:
    """(amount, the currency it is in) for one canonical balance row.

    Broker cash (IBKR Flex) is taken in the Flex base currency, the same figure
    as the NAV's cash (#144: it used to be converted again from the account's
    currency). Every other balance is its statement amount in its own currency,
    converted at the anchor's rate (D-30): an upload stores that amount
    unconverted in ``balance_base`` too, so reading the base value with the
    account's currency would treat a foreign-currency balance as already
    converted (#130 2.8)."""
    if row.get("account_base_currency"):
        return D(row.get("balance_base")), str(row["account_base_currency"]).upper()
    if row.get("balance_local") is not None and row.get("currency"):
        return D(row["balance_local"]), str(row["currency"]).upper()
    return D(row.get("balance_base")), _canonical_base_currency(row, fallback_currency)


def _canonical_cash_value(row: Dict[str, Any], rates: Mapping[str, Any], fallback_currency: str) -> Decimal:
    amount, currency = _cash_row_amount(row, fallback_currency)
    return amount * D(rates.get(currency))


@valuation_cached(shared=True)
def _credit_card_account_ids(db: Session, current_user_id: int) -> set[int]:
    """The user's credit-card accounts: their balances are liabilities, not cash
    (the same set _credit_card_liability_component returns). A card is any account
    whose account_type is CREDIT_CARD, with or without a credit_card_accounts row
    (#180)."""
    rows = db.execute(
        text(
            """
            SELECT a.id AS account_id
            FROM accounts a
            WHERE a.account_type = 'CREDIT_CARD'
              AND """
            + account_scope_sql("a")
        ),
        {"current_user_id": current_user_id},
    ).mappings().all()
    return {int(row["account_id"]) for row in rows}


def _cash_balance_rows(db: Session, *, current_user_id: int, anchor_date: date) -> List[Dict[str, Any]]:
    """The canonical balance rows that can count as cash: every account's except
    credit cards' (#180). A CREDIT_CARD account's balance is never cash, whether or
    not it has a credit_card_accounts row; a bank statement stored on a card account
    by mistake must not add to Cash. _cash_positions builds on this."""
    card_ids = _credit_card_account_ids(db, current_user_id)
    return [
        row
        for row in canonical_account_balance_rows(db, current_user_id=current_user_id, anchor_date=anchor_date)
        if row.get("account_id") is None or int(row["account_id"]) not in card_ids
    ]


# ─── Cash: one scope for every reader (#144) ─────────────────────────────────
CASH_BALANCE_TYPES = frozenset({"cash", "broker_cash", "bank_cash", "credit_balance", "loan_balance", "stablecoin_cash"})
CASH_SCOPE_NET_WORTH = "net_worth"  # what net worth counts as cash
CASH_SCOPE_CASH_PAGE = "cash_page"  # net-worth cash plus stablecoins (net worth counts those as crypto)
CASH_KIND_BALANCE = "balance"  # an account's own balance rows (bank, upload, broker without NAV)
CASH_KIND_NAV = "nav"  # the cash of an account valued by its NAV (IBKR Flex)
CASH_KIND_STABLECOIN = "stablecoin"
_NAV_CASH_TOLERANCE = Decimal("0.005")  # base-currency units: below this the NAV's cash rows "add up"


def _wallet_valuation(db: Session, anchor_ts: datetime, current_user_id: int, *, price_overlay: bool) -> Dict[str, Any]:
    """The crypto valuation net worth uses at this anchor; allocation and geography
    use the same one so their totals add up to net worth's.

    With the price overlay, "now" (an anchor on today's date) reads the newest
    valuation; an earlier anchor, such as the "since last update" compare side,
    reads the valuation as of its date, else both sides read the same one and
    crypto never moves (#206)."""
    if price_overlay and clock._local_date(anchor_ts) >= clock._app_today():
        return latest_wallet_valuation(db, current_user_id)
    return latest_wallet_valuation(db, current_user_id, as_of_date=anchor_ts.date())


def _stablecoin_rows_by_chain(db: Session, anchor_date: date, current_user_id: int) -> List[Dict[str, Any]]:
    return [
        dict(row)
        for row in db.execute(
            text(
                """
                WITH latest AS (
                  SELECT wallet_id, MAX(as_of_date) AS as_of_date
                  FROM crypto_wallet_snapshots
                  WHERE as_of_date <= :as_of_date
                  GROUP BY wallet_id
                )
                SELECT
                  i.chain AS source,
                  SUM(i.value_usd) AS value_usd,
                  MAX(s.as_of_date) AS as_of_date
                FROM crypto_wallet_snapshots s
                JOIN latest l ON l.wallet_id = s.wallet_id AND l.as_of_date = s.as_of_date
                JOIN crypto_wallets w ON w.id = s.wallet_id
                JOIN crypto_wallet_snapshot_items i ON i.snapshot_id = s.id
                WHERE w.status = 'active'
                  AND """
                + account_scope_sql("w")
                + """
                  AND UPPER(COALESCE(i.symbol, '')) IN ('USDC', 'USDT')
                GROUP BY i.chain
                ORDER BY i.chain
                """
            ),
            {"as_of_date": anchor_date, "current_user_id": current_user_id},
        ).mappings().all()
    ]


@valuation_cached(shared=True, date_args=("anchor_ts",))
def _cash_positions(
    db: Session,
    anchor_ts: datetime,
    base_currency: str,
    current_user_id: int,
    *,
    scope: str = CASH_SCOPE_NET_WORTH,
) -> List[Dict[str, Any]]:
    """The user's cash at ``anchor_ts`` in ``base_currency``: the one cash function
    behind net worth, the Cash page, its trend and History, allocation, geography
    and the cash freshness (#144).

    Scope ``net_worth``:
    - every non-card account's (#180) balance rows of a cash type, except
    - accounts valued by an IBKR NAV: their cash is the NAV's cash, split by
      currency with the broker cash rows of the NAV's own report date; whatever
      those rows don't cover is one entry in the NAV's base currency, so the sum
      is always the NAV's cash.
    Scope ``cash_page``: the same plus stablecoins (USDC/USDT) in active wallets,
    per chain.

    Each entry: kind (balance | nav | stablecoin), balance_type, account_id, platform,
    platform_type, country, currency (what the money is held in), value (in
    ``base_currency``), as_of_date. A currency with no FX rate is valued 0 and
    flagged by fx_status (D-30).
    """
    if scope not in (CASH_SCOPE_NET_WORTH, CASH_SCOPE_CASH_PAGE):
        raise ValueError(f"unknown cash scope {scope!r}")
    anchor_date = anchor_ts.date()
    balance_rows = [
        row
        for row in _cash_balance_rows(db, current_user_id=current_user_id, anchor_date=anchor_date)
        if str(row.get("balance_type") or "").lower() in CASH_BALANCE_TYPES
    ]
    nav_rows = latest_authoritative_nav_by_legacy_account(db, current_user_id=current_user_id, anchor_date=anchor_date)
    nav_account_ids = {int(row["legacy_account_id"]) for row in nav_rows if row.get("legacy_account_id") is not None}
    stablecoins = _stablecoin_rows_by_chain(db, anchor_date, current_user_id) if scope == CASH_SCOPE_CASH_PAGE else []

    currencies = {_cash_row_amount(row, base_currency)[1] for row in balance_rows}
    currencies.update(str(row.get("base_currency") or base_currency).upper() for row in nav_rows)
    if stablecoins:
        currencies.add("USD")
    rates = fx.get_rates(anchor_ts, base_currency, currencies) if currencies else {}

    def _entry(kind: str, row: Dict[str, Any], *, currency: str, value: Decimal, as_of: Any, country: Any) -> Dict[str, Any]:
        return {
            "kind": kind,
            "balance_type": str(row.get("balance_type") or "broker_cash").lower(),
            "account_id": int(row["account_id"]) if row.get("account_id") is not None else None,
            "platform": row.get("platform"),
            "platform_type": row.get("platform_type"),
            "country": country,
            "currency": currency,
            "value": value,
            "as_of_date": as_of,
        }

    nav_entries: List[Dict[str, Any]] = []
    out: List[Dict[str, Any]] = []
    for row in balance_rows:
        if row.get("account_id") is not None and int(row["account_id"]) in nav_account_ids:
            continue
        out.append(
            _entry(
                CASH_KIND_BALANCE,
                row,
                currency=str(row.get("currency") or base_currency).upper(),
                value=_canonical_cash_value(row, rates, base_currency),
                as_of=row.get("as_of_date"),
                country=row.get("platform_country"),
            )
        )

    for nav in nav_rows:
        if nav.get("legacy_account_id") is None:
            continue
        account_id = int(nav["legacy_account_id"])
        nav_currency = str(nav.get("base_currency") or base_currency).upper()
        rate = D(rates.get(nav_currency))
        nav_cash = D(nav.get("cash_base"))
        report_date = _date_only(nav.get("report_date"))
        same_day = [
            row
            for row in balance_rows
            if row.get("account_id") is not None
            and int(row["account_id"]) == account_id
            and row.get("broker_account_id") is not None
            and int(row["broker_account_id"]) == int(nav["broker_account_id"])
            and str(row.get("account_base_currency") or "").upper() == nav_currency
            and _date_only(row.get("as_of_date")) == report_date
        ]
        base = {
            "account_id": account_id,
            "platform": (same_day[0].get("platform") if same_day else None) or nav.get("platform"),
            "platform_type": nav.get("platform_type"),
        }
        amounts: Dict[str, Decimal] = {}
        as_of_by_currency: Dict[str, Any] = {}
        for row in same_day:
            currency = str(row.get("currency") or nav_currency).upper()
            amounts[currency] = amounts.get(currency, ZERO) + D(row.get("balance_base"))
            as_of_by_currency[currency] = row.get("as_of_date")
        # Whatever the rows don't cover (a missing row, or IBKR's own rounding of
        # the NAV) is held in the NAV's base currency, so the entries add up to
        # exactly the NAV's cash, the figure net worth has always used.
        remainder = nav_cash - sum(amounts.values())
        if nav_currency in amounts or abs(remainder) > _NAV_CASH_TOLERANCE or not amounts:
            amounts[nav_currency] = amounts.get(nav_currency, ZERO) + remainder
        else:
            # No row in the base currency and only rounding left: fold it into the largest.
            largest = max(amounts, key=lambda c: abs(amounts[c]))
            amounts[largest] += remainder
        for currency, amount in amounts.items():
            if amount == 0:
                continue
            nav_entries.append(
                _entry(
                    CASH_KIND_NAV,
                    base,
                    currency=currency,
                    value=amount * rate,
                    as_of=as_of_by_currency.get(currency) or (_iso_value(report_date) if report_date else nav.get("report_date")),
                    country=nav.get("country"),
                )
            )

    # Account order, as the canonical rows come (a tie in the freshness labels
    # resolves the same way it always has).
    out = sorted(nav_entries + out, key=lambda entry: entry["account_id"] if entry["account_id"] is not None else -1)
    usd_rate = D(rates.get("USD"))
    for row in stablecoins:
        if row.get("value_usd") is None:
            continue
        out.append(
            {
                "kind": CASH_KIND_STABLECOIN,
                "balance_type": "stablecoin_cash",
                "account_id": None,
                "platform": row.get("source"),
                "platform_type": "WALLET_PROVIDER",
                "country": "US",
                "currency": "USD",
                "value": D(row["value_usd"]) * usd_rate,
                "as_of_date": row.get("as_of_date"),
            }
        )
    return out


