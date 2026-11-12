from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import CurrentUser, account_scope_sql, require_current_user
from app.db.session import get_db
from app.fx import FxRates, fx_status, get_rates, get_rates_by_date, rate_date
from app.valuation.clock import (
    _anchor_ts,
    _date_only,
    _app_today,
    _transaction_in_month_window,
    _transaction_month_key,
    _transaction_query_bounds,
)
from app.valuation.facts import _networth_components
from app.portfolio.canonical_reads import canonical_snapshot_coverage_as_of
from app.valuation.state import _effective_as_of
from app.ingestion.card_balances import write_card_statement_balance
from app.valuation.card_ledger import card_ledgers
from app.valuation.card_dues import DueState, card_due_states, due_states, load_due_records, write_due
from app.valuation.card_payments import card_last4s, mark_own_card_payments
from app.valuation.own_transfers import OWN_TRANSFER_MATCH_DAYS, mark_own_transfers, owner_name_words
from app.schemas.spending import (
    CashFlowYearOverYearOut,
    CreditCardBalanceIn,
    CreditCardDueIn,
    CreditCardBalanceItem,
    CreditCardBalancePeriod,
    CreditCardBalancesOut,
    CategoryAmount,
    CashFlowAnalyticsOut,
    CashFlowBreakdownItem,
    CashFlowCategoryDeltaItem,
    CashFlowComparisonOut,
    CashFlowDiagnosticAnswer,
    CashFlowDetailOut,
    CashFlowDetailSection,
    CashFlowMerchantItem,
    CashFlowTrendOut,
    CashFlowTrendPoint,
    CashFlowTransactionItem,
    CashFlowWaterfallOut,
    CreditCardSummaryOut,
    CreditCardItem,
    CreditCardDetailOut,
    CreditCardTransactionItem,
    CreditCardRecurringPaymentItem,
    CreditCardAnalyticsOut,
    CreditCardAnalyticsCardItem,
    CreditCardAnalyticsTrendPoint,
    SpendingSummaryOut,
)

router = APIRouter(prefix="/spending", tags=["spending"], dependencies=[Depends(require_current_user)])
INCOME_TYPES = ("INCOME",)
EXPENSE_TYPES = ("EXPENSE", "FEE", "TAX", "INTEREST")
TRANSFER_TYPES = ("TRANSFER",)
EXPLICIT_TRANSFER_RAW_CATEGORIES = {
    "bank::transfer",
    "creditcard::payment",
    "brokerage::transfer",
}
LIKELY_INTERNAL_TRANSFER_MARKERS = (
    "IBKR",
    "INTERACTIVE BROKERS",
    "UOB",
    "OCBC",
    "POSB",
    "COINBASE",
    "OWN ACCOUNT",
    "CARD PAYMENT",
    "CREDIT CARD PAYMENT",
    "SI TO :",
    "REF:SALARY",
)
NON_OPERATING_COUNTERPARTY_MARKERS = (
    "PHILLIP SECURITIES",
    "DBS VICKERS",
    "VICKERS SECURITIES",
    "INTERACTIVE BROKERS",
    "IBKR",
    "GIRO PAYMENT",
    "ICT SELF",
)
FIXED_EXPENSE_KEYWORDS = (
    "rent",
    "mortgage",
    "utility",
    "utilities",
    "subscription",
    "insurance",
    "loan",
    "tax",
    "interest",
    "fee",
    "recurring",
    "internet",
    "phone",
)
RECURRING_KEYWORDS = (
    "rent",
    "mortgage",
    "utility",
    "utilities",
    "subscription",
    "insurance",
    "loan",
    "salary",
    "dividend",
    "interest",
    "recurring",
    "payroll",
)
SOURCE_KEYWORDS = {
    "salary": ("salary", "payroll", "bonus", "compensation"),
    "business": ("business", "freelance", "consult", "invoice"),
    "dividends": ("dividend",),
    "interest": ("interest",),
    "transfers": ("transfer",),
}


def _parse_month(month: str) -> datetime:
    try:
        return datetime.strptime(month + "-01", "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid month format. Use YYYY-MM, e.g. 2026-02")


def _add_months(dt: datetime, months: int) -> datetime:
    y = dt.year + (dt.month - 1 + months) // 12
    m = (dt.month - 1 + months) % 12 + 1
    return dt.replace(year=y, month=m)


def _month_end(dt: datetime) -> datetime:
    return _add_months(dt, 1)


def _clamp_day(dt: datetime, day: int) -> datetime:
    month_end = _month_end(dt)
    last_day = (month_end - timedelta(days=1)).day
    safe_day = min(day, last_day)
    return dt.replace(day=safe_day)


def _tx_iso(value: datetime | str) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).isoformat()
        return value.astimezone(timezone.utc).isoformat()
    try:
        return _row_ts(value).isoformat()
    except ValueError:
        pass
    return str(value)


def _row_ts(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _month_key(value: datetime | str) -> str:
    """The month a transaction counts in, by the user's calendar (#211, D-49):
    a date-only row (00:00 UTC) is its date's month, a timed one the month of
    its instant in the user's timezone. Month starts (00:00 UTC) map to
    themselves."""
    try:
        return _transaction_month_key(value)
    except ValueError:
        return str(value)[:7]


def _window_rows(db: Session, query, params: dict, start: datetime, end: datetime, *, start_key: str = "start"):
    """Rows of ``query`` whose transaction falls in the calendar window
    [start, end) in the user's timezone (#211): the SQL takes a day of slack
    either side and ``_transaction_in_month_window`` decides each row."""
    query_start, query_end = _transaction_query_bounds(start, end)
    rows = db.execute(query, {**params, start_key: query_start, "end": query_end}).mappings().all()
    return [row for row in rows if _transaction_in_month_window(row["ts"], start, end)]


def _cash_flow_rows(db: Session, start: datetime, end: datetime, current_user_id: int):
    cash_flow_q = text("""
        SELECT
          t.id AS transaction_id,
          t.ts,
          t.account_id,
          a.name AS account_name,
          a.account_type,
          t.amount,
          t.currency,
          t.type,
          t.category AS raw_category,
          COALESCE(override_ct.name, NULLIF(TRIM(t.category), ''), 'Uncategorized') AS resolved_category,
          COALESCE(override_ct.id, parser_ct.id) AS resolved_category_id,
          COALESCE(resolved_ct.code, '') AS resolved_category_code,
          COALESCE(resolved_parent_ct.code, '') AS resolved_parent_category_code,
          CASE
            WHEN co.source IS NOT NULL THEN co.source
            WHEN t.category IS NOT NULL
                 AND TRIM(t.category) <> ''
                 AND LOWER(TRIM(t.category)) <> 'uncategorized' THEN 'parser'
            ELSE 'uncategorized'
          END AS category_source,
          t.merchant_counterparty,
          t.notes,
          (SELECT display_name FROM users WHERE id = :current_user_id) AS owner_display_name
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
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
        LEFT JOIN category_taxonomy resolved_parent_ct
          ON resolved_parent_ct.id = resolved_ct.parent_id
        WHERE t.ts >= :start AND t.ts < :end
          AND """
            + account_scope_sql("a")
            + """
          AND t.type IN ('INCOME', 'EXPENSE', 'FEE', 'TAX', 'INTEREST', 'TRANSFER')
        ORDER BY t.ts DESC, t.id DESC
    """)
    # A few days either side, so an own-account transfer's other side is found across the
    # window's edge (#339); the rows returned are the window's only.
    slack = timedelta(days=OWN_TRANSFER_MATCH_DAYS)
    rows = _window_rows(db, cash_flow_q, {"current_user_id": current_user_id}, start - slack, end + slack)
    # A bank outflow that pays one of the user's own cards is a move between their accounts,
    # not spending: the card's charges are (#308, D-77).
    rows = mark_own_card_payments(rows, card_last4s(db, current_user_id))
    # Money between the user's own accounts (a standing instruction to themselves, the other
    # bank's credit of it) is neither income nor spending (#339, D-85).
    owner = owner_name_words(rows[0].get("owner_display_name")) if rows else frozenset()
    rows = mark_own_transfers(rows, owner, _is_transfer_like_before_own)
    return [row for row in rows if _transaction_in_month_window(row["ts"], start, end)]


def _is_transfer_like_before_own(row) -> bool:
    """Transfer-like by the rules that don't depend on own-transfer pairing (#339)."""
    return _is_transfer_resolved_category(row) or _is_non_operating_transfer_like(row)


def _is_transfer_resolved_category(row) -> bool:
    resolved_code = str(row.get("resolved_category_code") or "").strip().lower()
    parent_code = str(row.get("resolved_parent_category_code") or "").strip().lower()
    return resolved_code == "transfer" or parent_code == "transfer"


def _name_word_set(value: str | None) -> set[str]:
    return set(str(value or "").strip().lower().split())


def _is_self_named_counterparty(row) -> bool:
    """Catches deposits/transfers where the counterparty field is just the
    account owner's own name (e.g. a counter/ATM cash deposit slip), which
    are self-transfers between the owner's own accounts, not external income.
    Requires an exact word-set match (ignoring word order) so it only fires
    on bare-name counterparties and doesn't false-positive on merchant names
    that merely contain one of the owner's name words.
    """
    own_name = _name_word_set(row.get("owner_display_name"))
    if not own_name:
        return False
    return _name_word_set(row.get("merchant_counterparty")) == own_name


def _is_explicit_source_transfer(row) -> bool:
    if row.get("own_card_payment"):
        return True
    if row.get("own_transfer"):
        # Between the user's own accounts (#339): by name, or paired with its other side.
        return True
    raw_category = str(row.get("raw_category") or "").strip().lower()
    if raw_category in EXPLICIT_TRANSFER_RAW_CATEGORIES:
        return True
    if _is_self_named_counterparty(row):
        return True
    text = " ".join(
        [
            str(row.get("merchant_counterparty") or ""),
            str(row.get("notes") or ""),
        ]
    ).upper()
    if any(marker in text for marker in LIKELY_INTERNAL_TRANSFER_MARKERS):
        return True
    if any(marker in text for marker in NON_OPERATING_COUNTERPARTY_MARKERS):
        return True
    return False


def _is_non_operating_transfer_like(row) -> bool:
    if str(row.get("type") or "").upper() == "TRANSFER":
        return True
    return _is_explicit_source_transfer(row)


def _is_rent_outflow(row) -> bool:
    try:
        amount = float(row.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0.0
    if amount >= 0:
        return False
    return "rent" in _row_features(row)


def _cash_flow_bucket(row) -> str | None:
    if _is_rent_outflow(row):
        return "expense"
    if _is_transfer_resolved_category(row) or _is_non_operating_transfer_like(row):
        return None
    if row["type"] in INCOME_TYPES:
        return "income"
    if row["type"] in EXPENSE_TYPES:
        return "expense"
    if row["type"] in TRANSFER_TYPES:
        return None
    return None


def _normalize_text(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _build_row_rate_map(rows, base_currency: str) -> dict[date, FxRates]:
    """Rates for each row's own transaction date (D-30, #170): one store read for
    the whole range. A currency with no rate is left out (never 1.0), so its rows
    convert to 0 and the response's ``fx_status`` says so."""
    if not rows:
        return {}
    currencies = {(row["currency"] or base_currency).upper() for row in rows}
    return get_rates_by_date([_row_ts(row["ts"]) for row in rows], base_currency, currencies)


def _row_base_amount(row, base_currency: str, rates_by_date: dict[date, FxRates]) -> float:
    currency = (row["currency"] or base_currency).upper()
    rates = rates_by_date.get(rate_date(_row_ts(row["ts"])), {})
    return float(row["amount"]) * rates.get(currency, 0.0)


def _row_features(row) -> str:
    parts = [
        row.get("resolved_category"),
        row.get("raw_category"),
        row.get("resolved_category_code"),
        row.get("resolved_parent_category_code"),
        row.get("merchant_counterparty"),
        row.get("notes"),
        row.get("type"),
    ]
    return " ".join(_normalize_text(part) for part in parts if part)


def _bucket_magnitude(row, base_amount: float) -> float:
    return base_amount if _cash_flow_bucket(row) == "income" else -base_amount


def _is_recurring_row(row, merchant_months: dict[tuple[str, str], set[str]]) -> bool:
    merchant = _normalize_text(row.get("merchant_counterparty"))
    bucket = _cash_flow_bucket(row)
    if merchant and bucket and len(merchant_months.get((bucket, merchant), set())) >= 2:
        return True
    features = _row_features(row)
    return any(keyword in features for keyword in RECURRING_KEYWORDS)


def _expense_variability_label(row) -> str:
    features = _row_features(row)
    if any(keyword in features for keyword in FIXED_EXPENSE_KEYWORDS):
        return "Fixed"
    return "Variable"


def _inflow_source_label(row) -> str:
    features = _row_features(row)
    for label, keywords in SOURCE_KEYWORDS.items():
        if any(keyword in features for keyword in keywords):
            return label.title()
    return "Other"


# A card charge is a real repeat (#266): the trailing window it's judged over, in months
# (the selected month included).
RECURRING_LOOKBACK_MONTHS = 6


def _month_index(month: str) -> int:
    year, mon = month.split("-")
    return int(year) * 12 + int(mon) - 1


def detect_recurring_cadence(charges_by_month: dict[str, list[float]], month: str) -> str | None:
    """Whether one merchant's card charges are a real repeat (#266), and its cadence.

    ``charges_by_month``: ``YYYY-MM`` -> the positive charge amounts in that month, over the
    trailing window. A real repeat is billed like a subscription:
      - charged in the selected ``month``;
      - in at least 3 distinct months;
      - once a month at most (several charges in a month is shopping, not a subscription);
      - every month: consecutive months, with at most one missed month in between
        (a statement that landed late or a skipped cycle);
      - a stable amount: every charge within max(2, 10%) of their median.
    Returns ``"monthly"`` or ``None``. Quarterly or yearly charges can't show 3 times in
    the window, so they are never called recurring.
    """
    present = {m: [a for a in amounts if a > 0] for m, amounts in charges_by_month.items()}
    present = {m: a for m, a in present.items() if a}
    if month not in present or len(present) < 3:
        return None
    if any(len(amounts) > 1 for amounts in present.values()):
        return None
    indexes = sorted(_month_index(m) for m in present)
    gaps = [b - a for a, b in zip(indexes, indexes[1:])]
    if any(gap > 2 for gap in gaps) or sum(1 for gap in gaps if gap == 2) > 1:
        return None
    amounts = sorted(round(a[0], 2) for a in present.values())
    median = amounts[len(amounts) // 2]
    tolerance = max(2.0, median * 0.10)
    if not all(abs(amount - median) <= tolerance for amount in amounts):
        return None
    return "monthly"


def _sorted_breakdown_items(items: dict[str, float], total: float, limit: int | None = None) -> list[CashFlowBreakdownItem]:
    ranked = sorted(items.items(), key=lambda entry: (-entry[1], entry[0].lower()))
    if limit is not None:
        ranked = ranked[:limit]
    if total <= 0:
        return [
            CashFlowBreakdownItem(label=label, amount=amount, percent=0.0)
            for label, amount in ranked
        ]
    return [
        CashFlowBreakdownItem(label=label, amount=amount, percent=(amount / total))
        for label, amount in ranked
    ]


def _category_delta_items(current: dict[str, float], prior: dict[str, float], *, deterioration_only: bool = False) -> list[CashFlowCategoryDeltaItem]:
    items: list[CashFlowCategoryDeltaItem] = []
    labels = set(current) | set(prior)
    for label in labels:
        current_amount = current.get(label, 0.0)
        prior_amount = prior.get(label, 0.0)
        delta_amount = current_amount - prior_amount
        if deterioration_only and delta_amount <= 0:
            continue
        delta_percent = (delta_amount / prior_amount) if prior_amount else None
        if delta_amount > 0:
            direction = "deteriorated"
        elif delta_amount < 0:
            direction = "improved"
        else:
            direction = "flat"
        items.append(
            CashFlowCategoryDeltaItem(
                label=label,
                current_amount=current_amount,
                prior_amount=prior_amount,
                delta_amount=delta_amount,
                delta_percent=delta_percent,
                direction=direction,
            )
        )
    return sorted(items, key=lambda item: (-item.delta_amount, item.label.lower()))


def _month_metrics(rows, base_currency: str) -> dict[str, dict[str, float | None]]:
    month_rates = _build_row_rate_map(rows, base_currency)
    metrics: dict[str, dict[str, float | None]] = defaultdict(
        lambda: {
            "inflows": 0.0,
            "outflows": 0.0,
            "net": 0.0,
            "savings_rate": None,
            "burn_rate": None,
        }
    )

    for row in rows:
        bucket = _cash_flow_bucket(row)
        if bucket is None:
            continue
        month_key = _month_key(row["ts"])
        base_amount = _row_base_amount(row, base_currency, month_rates)
        if bucket == "income":
            metrics[month_key]["inflows"] = float(metrics[month_key]["inflows"] or 0.0) + base_amount
        else:
            metrics[month_key]["outflows"] = float(metrics[month_key]["outflows"] or 0.0) + (-base_amount)

    for month_key, values in metrics.items():
        inflows = float(values["inflows"] or 0.0)
        outflows = float(values["outflows"] or 0.0)
        net = inflows - outflows
        values["net"] = net
        values["savings_rate"] = (net / inflows) if inflows > 0 else None
        values["burn_rate"] = (outflows / inflows) if inflows > 0 else None

    return metrics


def _merchant_month_sets(rows) -> dict[tuple[str, str], set[str]]:
    months: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows:
        bucket = _cash_flow_bucket(row)
        merchant = _normalize_text(row.get("merchant_counterparty"))
        if bucket is None or not merchant:
            continue
        months[(bucket, merchant)].add(_month_key(row["ts"]))
    return months


def _cash_flow_trend(lookback_rows, month: str, base_currency: str) -> list[CashFlowTrendPoint]:
    """The six months ending at ``month``: inflows, outflows, net and rates per month.
    ``lookback_rows`` are ``_cash_flow_rows`` from five months before ``month`` to its
    end. One function for /cash-flow-detail's ``analytics.trend`` and
    /cash-flow-trend (#149), so the two can't drift."""
    trend_start = _add_months(_parse_month(month), -5)
    trend_end = _month_end(_parse_month(month))
    trend_rows = [
        row
        for row in lookback_rows
        if trend_start <= _parse_month(_month_key(row["ts"])) < trend_end
    ]
    trend_metrics = _month_metrics(trend_rows, base_currency)
    trend: list[CashFlowTrendPoint] = []
    for offset in range(6):
        point_month = _month_key(_add_months(trend_start, offset))
        values = trend_metrics.get(point_month, {})
        trend.append(
            CashFlowTrendPoint(
                month=point_month,
                inflows=float(values.get("inflows") or 0.0),
                outflows=float(values.get("outflows") or 0.0),
                net=float(values.get("net") or 0.0),
                savings_rate=values.get("savings_rate"),  # type: ignore[arg-type]
                burn_rate=values.get("burn_rate"),  # type: ignore[arg-type]
            )
        )
    return trend


def _deterioration_items(current: dict[str, float], prior: dict[str, float]) -> list[CashFlowCategoryDeltaItem]:
    """Categories whose net effect on free cash flow got worse (income down or
    spending up), worst first. ``current``/``prior`` are signed impacts per
    category: income positive, spending negative."""
    items: list[CashFlowCategoryDeltaItem] = []
    for label in set(current) | set(prior):
        current_value = current.get(label, 0.0)
        prior_value = prior.get(label, 0.0)
        delta = current_value - prior_value
        if delta >= 0:
            continue
        items.append(
            CashFlowCategoryDeltaItem(
                label=label,
                current_amount=current_value,
                prior_amount=prior_value,
                delta_amount=delta,
                delta_percent=(delta / prior_value) if prior_value not in (0, 0.0) else None,
                direction="deteriorated",
            )
        )
    items.sort(key=lambda item: (item.delta_amount, item.label.lower()))
    return items


def _days_in_month(month_start: datetime) -> int:
    return (_month_end(month_start) - timedelta(days=1)).day


@dataclass(frozen=True)
class _ComparisonWindow:
    """Which days of the month and of the month before a comparison counts (#243, D-63)."""

    basis: str  # "month_to_date" | "full_month"
    month_days: int
    through_day: int
    prior_month_start: datetime
    prior_month_days: int
    prior_through_day: int

    @property
    def prior_end(self) -> datetime:
        """The exclusive end of the prior window: 00:00 UTC of the day after its
        last counted day, as ``_transaction_in_month_window`` takes it."""
        return self.prior_month_start + timedelta(days=self.prior_through_day)


def _comparison_window(month_start: datetime, today: date) -> _ComparisonWindow:
    """Like-for-like comparison window for ``month_start`` given ``today`` (the
    user's date, ``_app_today``). The open month compares days 1..today with the
    previous month's days 1..today, clamped to that month's length (31 Mar vs
    February is all of February). Any other month: whole month vs whole month."""
    prior_month_start = _add_months(month_start, -1)
    month_days = _days_in_month(month_start)
    prior_month_days = _days_in_month(prior_month_start)
    if (today.year, today.month) == (month_start.year, month_start.month):
        through_day = today.day
        return _ComparisonWindow(
            basis="month_to_date",
            month_days=month_days,
            through_day=through_day,
            prior_month_start=prior_month_start,
            prior_month_days=prior_month_days,
            prior_through_day=min(through_day, prior_month_days),
        )
    return _ComparisonWindow(
        basis="full_month",
        month_days=month_days,
        through_day=month_days,
        prior_month_start=prior_month_start,
        prior_month_days=prior_month_days,
        prior_through_day=prior_month_days,
    )


def _period_flows(rows, base_currency: str) -> tuple[float, float, dict[str, float], dict[str, float]]:
    """Inflows, outflows, outflows per category and signed impact per category
    (income +, spending -) of ``rows``, each at its own date's FX rate."""
    rates = _build_row_rate_map(rows, base_currency)
    inflows = 0.0
    outflows = 0.0
    outflow_categories: dict[str, float] = defaultdict(float)
    impacts: dict[str, float] = defaultdict(float)
    for row in rows:
        bucket = _cash_flow_bucket(row)
        if bucket is None:
            continue
        amount = _bucket_magnitude(row, _row_base_amount(row, base_currency, rates))
        category = row["resolved_category"] or "Uncategorized"
        if bucket == "income":
            inflows += amount
            impacts[category] += amount
        elif bucket == "expense":
            outflows += amount
            outflow_categories[category] += amount
            impacts[category] -= amount
    return inflows, outflows, outflow_categories, impacts


def _year_over_year(
    *,
    month: str,
    year_ago_rows,
    base_currency: str,
    income_total: float,
    expense_total: float,
    net: float,
    outflow_categories: dict[str, float],
) -> CashFlowYearOverYearOut:
    """The month against the same month a year earlier (#409, U15, D-113), like for like: the
    open month is days 1..today against the same days last year (clamped to that month's
    length); any other month is whole month against whole month. ``year_ago_rows`` are
    ``_cash_flow_rows`` for the whole of last year's month."""
    month_start = _parse_month(month)
    year_ago_start = _add_months(month_start, -12)
    year_ago_days = _days_in_month(year_ago_start)
    today = _app_today()
    if (today.year, today.month) == (month_start.year, month_start.month):
        basis, through_day = "month_to_date", today.day
        prior_through = min(through_day, year_ago_days)
    else:
        basis, through_day = "full_month", _days_in_month(month_start)
        prior_through = year_ago_days
    prior_end = year_ago_start + timedelta(days=prior_through)
    rows = [row for row in year_ago_rows if _transaction_in_month_window(row["ts"], year_ago_start, prior_end)]
    prior_inflows, prior_outflows, prior_outflow_categories, _ = _period_flows(rows, base_currency)
    prior_net = prior_inflows - prior_outflows
    return CashFlowYearOverYearOut(
        basis=basis,
        month=month,
        prior_year_month=_month_key(year_ago_start),
        through_day=through_day,
        prior_start=year_ago_start.date().isoformat(),
        prior_end=(prior_end - timedelta(days=1)).date().isoformat(),
        has_prior_year_data=bool(year_ago_rows),
        inflows=income_total,
        outflows=expense_total,
        net=net,
        savings_rate=(net / income_total) if income_total > 0 else None,
        prior_inflows=prior_inflows,
        prior_outflows=prior_outflows,
        prior_net=prior_net,
        prior_savings_rate=(prior_net / prior_inflows) if prior_inflows > 0 else None,
        outflow_category_deltas=_category_delta_items(outflow_categories, prior_outflow_categories),
    )


def _savings_rate_trend(rows, month: str, base_currency: str) -> list[CashFlowTrendPoint]:
    """The twelve months ending at ``month`` (#409, U15): inflows, outflows, net and savings
    rate per month, oldest first, from ``_cash_flow_rows`` covering them."""
    start = _add_months(_parse_month(month), -11)
    metrics = _month_metrics(rows, base_currency)
    points: list[CashFlowTrendPoint] = []
    for offset in range(12):
        key = _month_key(_add_months(start, offset))
        values = metrics.get(key, {})
        points.append(
            CashFlowTrendPoint(
                month=key,
                inflows=float(values.get("inflows") or 0.0),
                outflows=float(values.get("outflows") or 0.0),
                net=float(values.get("net") or 0.0),
                savings_rate=values.get("savings_rate"),  # type: ignore[arg-type]
                burn_rate=values.get("burn_rate"),  # type: ignore[arg-type]
            )
        )
    return points


def _cash_flow_comparison(
    *,
    month: str,
    lookback_rows,
    prior_month_rows,
    base_currency: str,
    income_total: float,
    expense_total: float,
    net: float,
    outflow_categories: dict[str, float],
    category_impacts: dict[str, float],
) -> CashFlowComparisonOut:
    """The month's figures against the month before, like for like (#243, D-63)."""
    window = _comparison_window(_parse_month(month), _app_today())
    if window.basis == "full_month":
        prior_rows = prior_month_rows
    else:
        prior_rows = [
            row
            for row in lookback_rows
            if _transaction_in_month_window(row["ts"], window.prior_month_start, window.prior_end)
        ]
    prior_inflows, prior_outflows, prior_outflow_categories, prior_impacts = _period_flows(prior_rows, base_currency)
    prior_net = prior_inflows - prior_outflows
    return CashFlowComparisonOut(
        basis=window.basis,
        month=month,
        month_days=window.month_days,
        through_day=window.through_day,
        prior_month=_month_key(window.prior_month_start),
        prior_month_days=window.prior_month_days,
        prior_through_day=window.prior_through_day,
        prior_start=window.prior_month_start.date().isoformat(),
        prior_end=(window.prior_end - timedelta(days=1)).date().isoformat(),
        inflows=income_total,
        outflows=expense_total,
        net=net,
        savings_rate=(net / income_total) if income_total > 0 else None,
        prior_inflows=prior_inflows,
        prior_outflows=prior_outflows,
        prior_net=prior_net,
        prior_savings_rate=(prior_net / prior_inflows) if prior_inflows > 0 else None,
        inflows_change=income_total - prior_inflows,
        outflows_change=expense_total - prior_outflows,
        net_change=net - prior_net,
        outflow_category_deltas=_category_delta_items(outflow_categories, prior_outflow_categories, deterioration_only=True),
        deterioration_drivers=_deterioration_items(category_impacts, prior_impacts)[:5],
    )


# How far back the cash bridge can start: /cash-flow-detail loads transactions from five
# months before the month (``lookback_rows``), so an older start snapshot would miss flows.
CASH_BRIDGE_LOOKBACK_MONTHS = 5


def _cash_snapshot_date(db: Session, anchor_ts: datetime, current_user_id: int) -> date | None:
    """The newest cash fact (bank/broker/stablecoin balances, broker cash) at or before the
    anchor: the cash snapshot the bridge's starting or ending cash comes from (#265)."""
    as_of = canonical_snapshot_coverage_as_of(
        db,
        current_user_id=current_user_id,
        anchor_date=anchor_ts.date(),
        include_positions=False,
        include_nav=False,
    )
    # Postgres gives a date, SQLite (tests) a string.
    return _date_only(as_of)


def _cash_bridge_span(
    db: Session, month: str, prior_anchor: datetime, anchor: datetime, current_user_id: int
) -> tuple[date | None, date | None, bool, str | None]:
    """The cash bridge's period (#265, D-72): from the nearest cash snapshot at or before the
    month's start anchor to the nearest at or before its end anchor (for the open month: the
    newest so far). Exact snapshots on the anchors are no longer required.

    Returns (start, end, available, reason). Not available when either snapshot is missing,
    when there is no cash snapshot newer than the start one, or when the start is older than
    the transactions the page loads (CASH_BRIDGE_LOOKBACK_MONTHS)."""
    start = _cash_snapshot_date(db, prior_anchor, current_user_id)
    end = _cash_snapshot_date(db, anchor, current_user_id)
    floor = _add_months(_parse_month(month), -CASH_BRIDGE_LOOKBACK_MONTHS).date()
    if start is None or end is None:
        missing = prior_anchor if start is None else anchor
        return start, end, False, (
            f"The cash bridge needs a cash snapshot on or before {missing.date().isoformat()}; there is none yet. "
            "Upload a bank or broker statement that covers it."
        )
    if start >= end:
        return start, end, False, (
            f"No cash snapshot newer than {start.isoformat()} yet, so there is no period to bridge. "
            "Upload a newer bank or broker statement."
        )
    if start < floor:
        return start, end, False, (
            f"The nearest cash snapshot before this month is {start.isoformat()}, more than "
            f"{CASH_BRIDGE_LOOKBACK_MONTHS} months earlier, so the bridge would miss transactions."
        )
    return start, end, True, None


def _analytics_for_month(
    *,
    current_rows,
    lookback_rows,
    month: str,
    base_currency: str,
    current_user_id: int,
    db: Session,
    income_total: float,
    expense_total: float,
    net: float,
) -> CashFlowAnalyticsOut:
    current_month_rates = _build_row_rate_map(current_rows, base_currency)
    prior_month = _month_key(_add_months(_parse_month(month), -1))
    prior_rows = [row for row in lookback_rows if _month_key(row["ts"]) == prior_month]
    prior_month_rates = _build_row_rate_map(prior_rows, base_currency)
    merchant_months = _merchant_month_sets(lookback_rows)

    outflow_categories: dict[str, float] = defaultdict(float)
    inflow_categories: dict[str, float] = defaultdict(float)
    outflow_recurring_split: dict[str, float] = defaultdict(float)
    inflow_recurring_split: dict[str, float] = defaultdict(float)
    outflow_fixed_variable_split: dict[str, float] = defaultdict(float)
    inflow_source_mix: dict[str, float] = defaultdict(float)
    merchant_totals: dict[str, float] = defaultdict(float)
    merchant_counts: dict[str, int] = defaultdict(int)
    recurring_expense_categories: dict[str, float] = defaultdict(float)

    prior_outflow_categories: dict[str, float] = defaultdict(float)
    category_impacts_current: dict[str, float] = defaultdict(float)
    category_impacts_prior: dict[str, float] = defaultdict(float)

    for row in current_rows:
        bucket = _cash_flow_bucket(row)
        if bucket is None:
            continue
        base_amount = _row_base_amount(row, base_currency, current_month_rates)
        amount = _bucket_magnitude(row, base_amount)
        category = row["resolved_category"] or "Uncategorized"
        is_recurring = _is_recurring_row(row, merchant_months)
        recurring_label = "Recurring" if is_recurring else "One-off"

        if bucket == "income":
            inflow_categories[category] += amount
            inflow_recurring_split[recurring_label] += amount
            inflow_source_mix[_inflow_source_label(row)] += amount
            category_impacts_current[category] += amount
        elif bucket == "expense":
            outflow_categories[category] += amount
            outflow_recurring_split[recurring_label] += amount
            if is_recurring:
                recurring_expense_categories[category] += amount
            outflow_fixed_variable_split[_expense_variability_label(row)] += amount
            merchant = (row["merchant_counterparty"] or category or "Unknown").strip() or "Unknown"
            merchant_totals[merchant] += amount
            merchant_counts[merchant] += 1
            category_impacts_current[category] -= amount

    for row in prior_rows:
        bucket = _cash_flow_bucket(row)
        if bucket is None:
            continue
        base_amount = _row_base_amount(row, base_currency, prior_month_rates)
        amount = _bucket_magnitude(row, base_amount)
        category = row["resolved_category"] or "Uncategorized"
        if bucket == "expense":
            prior_outflow_categories[category] += amount
            category_impacts_prior[category] -= amount
        elif bucket == "income":
            category_impacts_prior[category] += amount

    trend = _cash_flow_trend(lookback_rows, month, base_currency)

    prior_metrics = _month_metrics(prior_rows, base_currency).get(
        prior_month,
        {"net": 0.0},
    )
    prior_inflows = float(prior_metrics.get("inflows") or 0.0)
    prior_outflows = float(prior_metrics.get("outflows") or 0.0)
    prior_net = float(prior_metrics.get("net") or 0.0)
    prior_savings_rate = prior_metrics.get("savings_rate")
    burn_rate = (expense_total / income_total) if income_total > 0 else None

    anchor = _anchor_ts(_parse_month(month))
    prior_anchor = _anchor_ts(_parse_month(prior_month))
    snapshot_start_as_of = _effective_as_of(db, prior_anchor, current_user_id)
    snapshot_end_as_of = _effective_as_of(db, anchor, current_user_id)
    boundary_exact = snapshot_start_as_of == prior_anchor and snapshot_end_as_of == anchor
    span_start, span_end, bridge_available, unavailable_reason = _cash_bridge_span(
        db, month, prior_anchor, anchor, current_user_id
    )
    # Valuation computes in Decimal (#360); this router works in floats.
    ending_cash = float(_networth_components(db, anchor, base_currency, current_user_id)["cash"])
    starting_cash = float(_networth_components(db, prior_anchor, base_currency, current_user_id)["cash"])
    transfers_and_funding = 0.0
    investment_and_fx_effects = None
    other_cash_movements = None
    if bridge_available and span_start is not None and span_end is not None:
        # The flows between the two cash snapshots, by the same boundary convention as before
        # (after the start date's midnight, up to the end date's midnight).
        window_start = datetime(span_start.year, span_start.month, span_start.day, tzinfo=timezone.utc)
        window_end = datetime(span_end.year, span_end.month, span_end.day, tzinfo=timezone.utc)
        reconciliation_rows = [
            row for row in lookback_rows if window_start < _row_ts(row["ts"]) <= window_end
        ]
    elif snapshot_start_as_of is not None and snapshot_end_as_of is not None:
        reconciliation_rows = [
            row
            for row in lookback_rows
            if snapshot_start_as_of < _row_ts(row["ts"]) <= snapshot_end_as_of
        ]
    else:
        reconciliation_rows = current_rows
    reconciliation_rates = _build_row_rate_map(reconciliation_rows, base_currency)
    operating_inflows_for_bridge = 0.0
    operating_outflows_for_bridge = 0.0
    for row in reconciliation_rows:
        base_amount = _row_base_amount(row, base_currency, reconciliation_rates)
        if _is_transfer_resolved_category(row) or _is_non_operating_transfer_like(row):
            transfers_and_funding += base_amount
            continue
        bucket = _cash_flow_bucket(row)
        if bucket == "income":
            operating_inflows_for_bridge += base_amount
        elif bucket == "expense":
            operating_outflows_for_bridge += -base_amount
    if starting_cash is not None and ending_cash is not None:
        investment_and_fx_effects = ending_cash - (
            starting_cash
            + operating_inflows_for_bridge
            - operating_outflows_for_bridge
            + transfers_and_funding
        )
        other_cash_movements = investment_and_fx_effects
    # #265: why the bridge can't be drawn, or None when it can (it no longer needs exact
    # snapshots on the anchors; span_start/span_end say which snapshots it uses).
    availability_message = unavailable_reason
    span_basis = None
    if bridge_available and span_start is not None and span_end is not None:
        span_basis = "exact" if span_start == prior_anchor.date() and span_end == anchor.date() else "nearest"

    top_outflow_merchants = sorted(
        merchant_totals.items(),
        key=lambda entry: (-entry[1], entry[0].lower()),
    )[:5]

    deterioration_items = _deterioration_items(category_impacts_current, category_impacts_prior)

    top_outflows = _sorted_breakdown_items(outflow_categories, expense_total, limit=3)
    recurring_outflows = _sorted_breakdown_items(recurring_expense_categories, expense_total, limit=3)
    inflow_mix = {
        item.label: item.percent
        for item in _sorted_breakdown_items(inflow_source_mix, income_total)
    }

    if income_total > 0:
        if net >= 0:
            saved_vs_spent_answer = (
                f"Saved {(net / income_total) * 100:.1f}% and spent {(expense_total / income_total) * 100:.1f}% of inflows."
            )
        else:
            overspend_amount = abs(net)
            saved_vs_spent_answer = (
                f"Saved 0.0% of inflows and spent 100.0% of them. "
                f"Outflows exceeded inflows by {overspend_amount:.0f}, which had to come from existing cash or other funding sources."
            )
    else:
        saved_vs_spent_answer = "No inflows were recorded, so savings and spend shares are unavailable."

    answers = [
        CashFlowDiagnosticAnswer(
            question="Where did my money go this month?",
            answer=(
                "Most outflows went to "
                + (
                    ", ".join(
                        f"{item.label} ({item.percent * 100:.1f}% / {item.amount:.0f})"
                        for item in top_outflows
                    )
                    if top_outflows
                    else "no recorded expense categories"
                )
                + "."
            ),
        ),
        CashFlowDiagnosticAnswer(
            question="What were my top spending categories this month?",
            answer=(
                ", ".join(
                    f"{item.label} at {item.amount:.0f}"
                    for item in top_outflows
                )
                if top_outflows
                else "No spending categories were recorded."
            ),
        ),
        CashFlowDiagnosticAnswer(
            question="How much of my income was saved vs spent?",
            answer=saved_vs_spent_answer,
        ),
        CashFlowDiagnosticAnswer(
            question="What changed versus last month?",
            answer=(
                f"Net cash flow was {net:.0f} this month versus {prior_net:.0f} in {prior_month}, "
                f"a {net - prior_net:+.0f} change. "
                f"Inflows changed by {income_total - prior_inflows:+.0f} and outflows changed by {expense_total - prior_outflows:+.0f}. "
                + (
                    f"Savings rate moved from {(float(prior_savings_rate) * 100):.1f}% to {((net / income_total) * 100):.1f}%."
                    if income_total > 0 and prior_savings_rate is not None
                    else "Savings-rate comparison is unavailable because one of the months has no recorded inflows."
                )
            ),
        ),
        CashFlowDiagnosticAnswer(
            question="Which recurring expenses are driving most of my outflows?",
            answer=(
                ", ".join(
                    f"{item.label} ({item.amount:.0f})"
                    for item in recurring_outflows[:3]
                )
                if recurring_outflows
                else "No recurring expense signal was detected."
            ),
        ),
        CashFlowDiagnosticAnswer(
            question="What percentage of inflows came from salary, dividends, and transfers?",
            answer=(
                f"Salary {inflow_mix.get('Salary', 0.0) * 100:.1f}%, "
                f"dividends {inflow_mix.get('Dividends', 0.0) * 100:.1f}%, "
                f"transfers {inflow_mix.get('Transfers', 0.0) * 100:.1f}%."
            ),
        ),
        CashFlowDiagnosticAnswer(
            question="Which categories explain most of the deterioration in free cash flow?",
            answer=(
                ", ".join(
                    f"{item.label} ({item.delta_amount:.0f})"
                    for item in deterioration_items[:3]
                )
                if deterioration_items
                else "No category-level deterioration versus last month was detected."
            ),
        ),
    ]

    return CashFlowAnalyticsOut(
        burn_rate=burn_rate,
        prior_month=prior_month,
        prior_month_net=prior_net,
        free_cash_flow_change_vs_prior_month=(net - prior_net),
        outflow_categories=_sorted_breakdown_items(outflow_categories, expense_total),
        inflow_categories=_sorted_breakdown_items(inflow_categories, income_total),
        outflow_recurring_split=_sorted_breakdown_items(outflow_recurring_split, expense_total),
        inflow_recurring_split=_sorted_breakdown_items(inflow_recurring_split, income_total),
        outflow_fixed_variable_split=_sorted_breakdown_items(outflow_fixed_variable_split, expense_total),
        inflow_source_mix=_sorted_breakdown_items(inflow_source_mix, income_total),
        top_outflow_merchants=[
            CashFlowMerchantItem(
                merchant=merchant,
                amount=amount,
                percent=(amount / expense_total) if expense_total > 0 else 0.0,
                transaction_count=merchant_counts[merchant],
            )
            for merchant, amount in top_outflow_merchants
        ],
        largest_inflow_drivers=_sorted_breakdown_items(inflow_categories, income_total, limit=5),
        outflow_category_deltas=_category_delta_items(outflow_categories, prior_outflow_categories, deterioration_only=True),
        deterioration_drivers=deterioration_items[:5],
        trend=trend,
        waterfall=CashFlowWaterfallOut(
            starting_cash=starting_cash,
            snapshot_start_as_of=_tx_iso(snapshot_start_as_of) if snapshot_start_as_of is not None else None,
            snapshot_start_boundary_at=_tx_iso(prior_anchor),
            inflows=operating_inflows_for_bridge,
            outflows=operating_outflows_for_bridge,
            transfers_and_funding=transfers_and_funding,
            investment_and_fx_effects=investment_and_fx_effects,
            other_cash_movements=other_cash_movements,
            snapshot_end_as_of=_tx_iso(snapshot_end_as_of) if snapshot_end_as_of is not None else None,
            snapshot_end_boundary_at=_tx_iso(anchor),
            boundary_exact=boundary_exact,
            availability_message=availability_message,
            bridge_available=bridge_available,
            span_start=span_start.isoformat() if span_start is not None else None,
            span_end=span_end.isoformat() if span_end is not None else None,
            span_basis=span_basis,
            ending_cash=ending_cash,
        ),
        answers=answers,
        comparison=_cash_flow_comparison(
            month=month,
            lookback_rows=lookback_rows,
            prior_month_rows=prior_rows,
            base_currency=base_currency,
            income_total=income_total,
            expense_total=expense_total,
            net=net,
            outflow_categories=outflow_categories,
            category_impacts=category_impacts_current,
        ),
    )


def _credit_cards(db: Session, current_user_id: int):
    cards_q = text("""
        SELECT
          a.id AS account_id,
          a.name AS account_name,
          a.currency AS account_currency,
          COALESCE(NULLIF(TRIM(cc.card_name), ''), a.name) AS card_name,
          COALESCE(NULLIF(TRIM(cc.issuer), ''), a.platform) AS issuer,
          COALESCE(cc.credit_limit, 0) AS credit_limit,
          cc.available_limit,
          cc.available_limit_as_of,
          COALESCE(cc.statement_day, 1) AS statement_day,
          COALESCE(cc.due_day, 1) AS due_day,
          cc.due_day AS configured_due_day
        FROM accounts a
        LEFT JOIN credit_card_accounts cc ON cc.account_id = a.id
        WHERE a.account_type = 'CREDIT_CARD'
          AND """
            + account_scope_sql("a")
            + """
        ORDER BY a.name
    """)
    return db.execute(cards_q, {"current_user_id": current_user_id}).mappings().all()


def _spend_by_account(
    db: Session,
    start: datetime,
    end: datetime,
    base_currency: str,
    current_user_id: int,
) -> dict[int, float]:
    spend_q = text("""
        SELECT
          t.account_id,
          t.ts,
          t.amount,
          t.currency
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        WHERE t.ts >= :start AND t.ts < :end
          AND a.account_type = 'CREDIT_CARD'
          AND """
            + account_scope_sql("a")
            + """
          AND t.type IN ('EXPENSE','FEE','TAX','INTEREST')
    """)
    spend_rows = _window_rows(db, spend_q, {"current_user_id": current_user_id}, start, end)
    rates_by_date = _build_row_rate_map(spend_rows, base_currency)
    spend: dict[int, float] = {}
    for row in spend_rows:
        converted = _row_base_amount(row, base_currency, rates_by_date)
        account_id = int(row["account_id"])
        spend[account_id] = spend.get(account_id, 0.0) + (-converted)
    return spend


def _credit_card_analytics_rows(db: Session, start: datetime, end: datetime, current_user_id: int):
    """Single bounded query over [start, end) for every EXPENSE_TYPES transaction on the
    user's owned CREDIT_CARD accounts, with resolved category attached. Callers slice this
    one result set by month bucket for the selected month, prior month, and trend window —
    no repeated round trips per month."""
    rows_q = text("""
        SELECT
          t.account_id,
          a.name AS account_name,
          COALESCE(NULLIF(TRIM(cc.card_name), ''), a.name) AS card_name,
          COALESCE(NULLIF(TRIM(cc.issuer), ''), a.platform) AS issuer,
          t.ts,
          t.amount,
          t.type,
          t.currency,
          t.category,
          COALESCE(ct.name, NULLIF(TRIM(t.category), ''), 'Uncategorized') AS resolved_category,
          CASE
            WHEN co.source IS NOT NULL THEN co.source
            WHEN t.category IS NOT NULL
                 AND TRIM(t.category) <> ''
                 AND LOWER(TRIM(t.category)) <> 'uncategorized' THEN 'parser'
            ELSE 'uncategorized'
          END AS category_source,
          t.merchant_counterparty,
          t.notes
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        LEFT JOIN credit_card_accounts cc ON cc.account_id = t.account_id
        LEFT JOIN category_overrides co ON co.transaction_id = t.id
        LEFT JOIN category_taxonomy ct ON ct.id = co.category_id
        WHERE t.ts >= :start AND t.ts < :end
          AND a.account_type = 'CREDIT_CARD'
          AND """
            + account_scope_sql("a")
            + """
          AND t.type IN ('EXPENSE','TAX','FEE','INTEREST')
        ORDER BY t.ts DESC, t.id DESC
    """)
    return _window_rows(db, rows_q, {"current_user_id": current_user_id}, start, end)


def _cc_transaction_item(row, base_amount: float) -> CreditCardTransactionItem:
    description = row["merchant_counterparty"] or row["resolved_category"] or row["category"] or "Transaction"
    return CreditCardTransactionItem(
        account_id=int(row["account_id"]),
        account_name=row["account_name"],
        card_name=row["card_name"],
        issuer=row["issuer"],
        ts=_tx_iso(row["ts"]),
        description=description,
        amount=base_amount,
        type=row["type"],
        category=row["category"],
        resolved_category=row["resolved_category"],
        category_source=row["category_source"],
        merchant_counterparty=row["merchant_counterparty"],
        notes=row["notes"],
    )


def _credit_card_recurring_payments(
    db: Session,
    current_user_id: int,
    month: str,
    base_currency: str,
    lookback_start: datetime,
    end: datetime,
    account_id: int | None = None,
) -> list[CreditCardRecurringPaymentItem]:
    """Merchants charged in the selected month that are a real repeat
    (``detect_recurring_cadence``, #266) over the trailing window from ``lookback_start``.
    Optionally scoped to a single owned CREDIT_CARD account."""
    recurring_q = text("""
        SELECT
          t.account_id,
          a.name AS account_name,
          COALESCE(NULLIF(TRIM(cc.card_name), ''), a.name) AS card_name,
          COALESCE(NULLIF(TRIM(cc.issuer), ''), a.platform) AS issuer,
          t.ts,
          t.amount,
          t.currency,
          t.merchant_counterparty
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        LEFT JOIN credit_card_accounts cc ON cc.account_id = t.account_id
        WHERE t.ts >= :lookback_start AND t.ts < :end
          AND a.account_type = 'CREDIT_CARD'
          AND """
            + account_scope_sql("a")
            + """
          AND t.type = 'EXPENSE'
          AND COALESCE(TRIM(t.merchant_counterparty), '') <> ''"""
            + (" AND t.account_id = :account_id" if account_id is not None else "")
            + """
        ORDER BY t.ts DESC, t.id DESC
    """)
    params: dict = {"current_user_id": current_user_id}
    if account_id is not None:
        params["account_id"] = account_id
    recurring_rows = _window_rows(db, recurring_q, params, lookback_start, end, start_key="lookback_start")
    recurring_rates = _build_row_rate_map(recurring_rows, base_currency)

    recurring_index: dict[tuple[int, str], dict] = {}
    for row in recurring_rows:
        merchant = str(row["merchant_counterparty"]).strip()
        key = (int(row["account_id"]), merchant)
        converted = _row_base_amount(row, base_currency, recurring_rates)
        record = recurring_index.setdefault(
            key,
            {
                "account_id": int(row["account_id"]),
                "account_name": row["account_name"],
                "card_name": row["card_name"],
                "issuer": row["issuer"],
                "merchant_counterparty": merchant,
                "months": set(),
                "monthly_amounts": defaultdict(float),
                "charges_by_month": defaultdict(list),
                "current_month_amount": 0.0,
            },
        )
        month_key = _month_key(row["ts"])
        amount = -converted
        record["months"].add(month_key)
        record["monthly_amounts"][month_key] += amount
        record["charges_by_month"][month_key].append(amount)
        if month_key == month:
            record["current_month_amount"] += amount

    recurring_payments: list[CreditCardRecurringPaymentItem] = []
    for record in recurring_index.values():
        months_present = len(record["months"])
        current_month_amount = float(record["current_month_amount"])
        cadence = detect_recurring_cadence(record["charges_by_month"], month)
        if current_month_amount <= 0 or cadence is None:
            continue
        amounts = sorted(a for charges in record["charges_by_month"].values() for a in charges if a > 0)
        recurring_payments.append(
            CreditCardRecurringPaymentItem(
                account_id=record["account_id"],
                account_name=record["account_name"],
                card_name=record["card_name"],
                issuer=record["issuer"],
                merchant_counterparty=record["merchant_counterparty"],
                months_present=months_present,
                current_month_amount=current_month_amount,
                cadence=cadence,
                typical_amount=float(amounts[len(amounts) // 2]),
            )
        )

    recurring_payments.sort(
        key=lambda item: (item.current_month_amount, item.merchant_counterparty.lower()),
        reverse=True,
    )
    return recurring_payments


def _card_due_fields(card, dues: dict[int, DueState], start: datetime) -> tuple[str | None, str | None, str | None]:
    """(due_date, due_source, due_status) for one card (#352, D-94): the due date its newest
    statement printed or its owner typed in; else the configured due day in the month
    (credit_card_accounts); else unknown. Never a default day."""
    state = dues.get(int(card["account_id"]))
    if state is not None:
        return state.due_date.isoformat(), state.source, state.status
    if card["configured_due_day"]:
        return _clamp_day(start, int(card["due_day"])).date().isoformat(), "configured", None
    return None, None, None


def _credit_card_items(
    cards,
    spend_by_account: dict[int, float],
    start: datetime,
    base_currency: str,
    dues: dict[int, DueState] | None = None,
) -> list[CreditCardItem]:
    account_currencies = {(c["account_currency"] or base_currency).upper() for c in cards}
    account_rates = get_rates(start, base_currency, account_currencies)
    items: list[CreditCardItem] = []
    for card in cards:
        account_currency = (card["account_currency"] or base_currency).upper()
        rate = account_rates.get(account_currency, 0.0)
        credit_limit = float(card["credit_limit"]) * rate
        available_limit = (
            float(card["available_limit"]) * rate
            if card["available_limit"] is not None
            else None
        )
        if available_limit is not None and card["available_limit_as_of"] is not None:
            current_due = max(credit_limit - available_limit, 0.0)
            current_due_source = "available_limit"
        else:
            current_due = spend_by_account.get(int(card["account_id"]), 0.0)
            current_due_source = "transactions"
        utilization = (current_due / credit_limit) if credit_limit > 0 else None
        due_date, due_source, due_status = _card_due_fields(card, dues or {}, start)
        items.append(
            CreditCardItem(
                account_id=int(card["account_id"]),
                account_name=card["account_name"],
                card_name=card["card_name"],
                issuer=card["issuer"],
                credit_limit=credit_limit,
                available_limit=available_limit,
                available_limit_as_of=(
                    _tx_iso(card["available_limit_as_of"])
                    if card["available_limit_as_of"] is not None
                    else None
                ),
                current_due_source=current_due_source,
                statement_day=int(card["statement_day"]),
                due_day=int(card["due_day"]),
                due_date=due_date,
                current_due=current_due,
                utilization=utilization,
                due_source=due_source,
                due_status=due_status,
            )
        )
    return items


@router.get("/summary", response_model=SpendingSummaryOut)
def spending_summary(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    start = _parse_month(month)
    end = _month_end(start)
    rows = _cash_flow_rows(db, start, end, current_user.id)
    rates_by_date = _build_row_rate_map(rows, base_currency)

    income_total = 0.0
    expense_total = 0.0
    income_categories: dict[str, float] = {}
    expense_categories: dict[str, float] = {}
    for r in rows:
        amount = _row_base_amount(r, base_currency, rates_by_date)
        category = r["resolved_category"] or "Uncategorized"
        bucket = _cash_flow_bucket(r)
        if bucket == "income":
            income_total += amount
            income_categories[category] = income_categories.get(category, 0.0) + amount
        elif bucket == "expense":
            expense_total += -amount
            expense_categories[category] = expense_categories.get(category, 0.0) + (-amount)
    net = income_total - expense_total
    savings_rate = (net / income_total) if income_total > 0 else None

    income_categories_list = [
        CategoryAmount(category=k, amount=v) for k, v in income_categories.items() if v > 0
    ]
    expense_categories_list = [
        CategoryAmount(category=k, amount=v) for k, v in expense_categories.items() if v > 0
    ]

    return SpendingSummaryOut(
        month=month,
        base_currency=base_currency,
        income_total=income_total,
        expense_total=expense_total,
        net=net,
        savings_rate=savings_rate,
        income_categories=income_categories_list,
        expense_categories=expense_categories_list,
        **fx_status(),
    )


@router.get("/cash-flow-detail", response_model=CashFlowDetailOut)
def cash_flow_detail(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    start = _parse_month(month)
    end = _month_end(start)
    lookback_start = _add_months(start, -5)
    lookback_rows = _cash_flow_rows(db, lookback_start, end, current_user.id)
    rows = [row for row in lookback_rows if _month_key(row["ts"]) == month]
    rates_by_date = _build_row_rate_map(rows, base_currency)

    income_total = 0.0
    expense_total = 0.0
    income_transactions: list[CashFlowTransactionItem] = []
    expense_transactions: list[CashFlowTransactionItem] = []

    for row in rows:
        currency = (row["currency"] or base_currency).upper()
        base_amount = _row_base_amount(row, base_currency, rates_by_date)
        item = CashFlowTransactionItem(
            transaction_id=int(row["transaction_id"]),
            ts=_tx_iso(row["ts"]),
            account_id=int(row["account_id"]),
            account_name=row["account_name"],
            account_type=row["account_type"],
            amount=float(row["amount"]),
            currency=currency,
            base_amount=base_amount,
            type=row["type"],
            raw_category=row["raw_category"],
            resolved_category=row["resolved_category"] or "Uncategorized",
            resolved_category_id=(
                int(row["resolved_category_id"])
                if row["resolved_category_id"] is not None
                else None
            ),
            category_source=row["category_source"] or "uncategorized",
            merchant_counterparty=row["merchant_counterparty"],
            notes=row["notes"],
        )
        bucket = _cash_flow_bucket(row)
        if bucket == "income":
            income_total += base_amount
            income_transactions.append(item)
        elif bucket == "expense":
            expense_total += -base_amount
            expense_transactions.append(item)

    net = income_total - expense_total
    savings_rate = (net / income_total) if income_total > 0 else None

    analytics = _analytics_for_month(
        current_rows=rows,
        lookback_rows=lookback_rows,
        month=month,
        base_currency=base_currency,
        current_user_id=current_user.id,
        db=db,
        income_total=income_total,
        expense_total=expense_total,
        net=net,
    )
    # #409 (U15): last year's same month and a twelve-month savings-rate line. The rows before
    # the five-month lookback come from one more read, with the same own-transfer rules (D-85).
    older_rows = _cash_flow_rows(db, _add_months(start, -12), lookback_start, current_user.id)
    year_ago_key = _month_key(_add_months(start, -12))
    current_outflow_categories = {item.label: item.amount for item in analytics.outflow_categories}
    analytics.year_over_year = _year_over_year(
        month=month,
        year_ago_rows=[row for row in older_rows if _month_key(row["ts"]) == year_ago_key],
        base_currency=base_currency,
        income_total=income_total,
        expense_total=expense_total,
        net=net,
        outflow_categories=current_outflow_categories,
    )
    analytics.savings_rate_trend = _savings_rate_trend(list(older_rows) + list(lookback_rows), month, base_currency)

    return CashFlowDetailOut(
        month=month,
        base_currency=base_currency,
        income_total=income_total,
        expense_total=expense_total,
        net=net,
        savings_rate=savings_rate,
        calculation=(
            "Net = income_total - expense_total using month-scoped transactions with types "
            "INCOME, EXPENSE, FEE, TAX, INTEREST, TRANSFER. Rows resolved under Transfer "
            "categories or explicit source transfer categories are excluded."
        ),
        analytics=analytics,
        income=CashFlowDetailSection(
            total=income_total,
            transaction_count=len(income_transactions),
            included_types=list(INCOME_TYPES),
            transactions=income_transactions,
        ),
        expenses=CashFlowDetailSection(
            total=expense_total,
            transaction_count=len(expense_transactions),
            included_types=list(EXPENSE_TYPES),
            transactions=expense_transactions,
        ),
        **fx_status(),
    )


@router.get("/cash-flow-trend", response_model=CashFlowTrendOut)
def cash_flow_trend(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    """Lean twin of /cash-flow-detail (#149): its ``analytics.trend`` only, the same
    numbers, without the month's transactions, breakdowns or cash reconciliation."""
    start = _parse_month(month)
    lookback_rows = _cash_flow_rows(db, _add_months(start, -5), _month_end(start), current_user.id)
    return CashFlowTrendOut(
        month=month,
        base_currency=base_currency,
        trend=_cash_flow_trend(lookback_rows, month, base_currency),
        **fx_status(),
    )


@router.get("/credit-cards", response_model=CreditCardSummaryOut)
def credit_card_summary(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    start = _parse_month(month)
    end = _month_end(start)

    cards = _credit_cards(db, current_user.id)
    spend = _spend_by_account(db, start, end, base_currency, current_user.id)
    items = _credit_card_items(cards, spend, start, base_currency, card_due_states(db, current_user.id, today=_app_today()))

    total_spend = sum(i.current_due for i in items)
    return CreditCardSummaryOut(
        month=month,
        base_currency=base_currency,
        total_spend=total_spend,
        cards=items,
        **fx_status(),
    )


@router.get("/credit-card-balances", response_model=CreditCardBalancesOut)
def credit_card_balances(
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    """Each card's running balance (#300, D-76): what it owes now, its newest dated
    balance, what was paid since and whether that paid it in full, fees and interest
    this year, and every statement period checked against the card's transactions."""
    today = _app_today()
    cards = {int(c["account_id"]): c for c in _credit_cards(db, current_user.id)}
    ledgers = card_ledgers(db, current_user.id, today=today)
    dues = due_states(load_due_records(db, current_user.id, today=today), ledgers, today=today)
    rates = get_rates(datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc), base_currency,
                      {ledger.currency for ledger in ledgers})

    def _iso(day: date | None) -> str | None:
        return day.isoformat() if day else None

    items: list[CreditCardBalanceItem] = []
    for ledger in ledgers:
        card = cards.get(ledger.account_id)
        if card is None:
            continue
        due_date = None
        due_source = None
        state = dues.get(ledger.account_id)
        if state is not None:
            # #352: the due date the newest statement printed (or its owner typed in from it).
            due_date = state.due_date.isoformat()
            due_source = state.source
        elif ledger.last_balance_date is not None and ledger.paid_in_full is False and card["configured_due_day"]:
            # The configured due day after the newest statement (credit_card_accounts).
            due = _clamp_day(datetime.combine(ledger.last_balance_date, datetime.min.time(), tzinfo=timezone.utc),
                             int(card["due_day"]))
            if due.date() <= ledger.last_balance_date:
                due = _clamp_day(_add_months(due.replace(day=1), 1), int(card["due_day"]))
            due_date = due.date().isoformat()
            due_source = "configured"
        items.append(
            CreditCardBalanceItem(
                account_id=ledger.account_id,
                account_name=card["account_name"],
                card_name=card["card_name"],
                issuer=card["issuer"],
                currency=ledger.currency,
                method=ledger.method,
                owed_now=ledger.owed_now,
                owed_now_base=round(ledger.owed_now * rates.get(ledger.currency, 0.0), 2),
                last_balance_date=_iso(ledger.last_balance_date),
                last_balance=ledger.last_balance,
                last_balance_source=ledger.last_balance_source,
                paid_since=ledger.paid_since,
                charges_since=ledger.charges_since,
                paid_in_full=ledger.paid_in_full,
                due_date=due_date,
                due_source=due_source,
                due_statement_date=_iso(state.statement_date) if state else None,
                amount_due=state.amount_due if state else None,
                minimum_due=state.minimum_due if state else None,
                paid_toward_due=state.paid if state else None,
                remaining_due=state.remaining if state else None,
                due_status=state.status if state else None,
                minimum_paid=state.minimum_paid if state else None,
                fees_interest_ytd=ledger.fees_interest_ytd,
                last_transaction_date=_iso(ledger.last_transaction_date),
                flagged_count=ledger.flagged_count,
                periods=[
                    CreditCardBalancePeriod(
                        from_date=period.from_date.isoformat(),
                        to_date=_iso(period.to_date),
                        opening=round(period.opening, 2),
                        charges=round(period.charges, 2),
                        fees=round(period.fees, 2),
                        interest=round(period.interest, 2),
                        payments=round(period.payments, 2),
                        credits=round(period.credits, 2),
                        transaction_count=period.transaction_count,
                        expected=period.expected,
                        printed=period.printed,
                        difference=period.difference,
                        flagged=period.flagged,
                        paid_in_full=period.paid_in_full,
                        bank_payments=round(period.bank_payments, 2),
                        note=period.note,
                    )
                    for period in reversed(ledger.periods)
                ],
            )
        )
    return CreditCardBalancesOut(
        base_currency=base_currency,
        as_of=today.isoformat(),
        total_owed_base=round(sum(item.owed_now_base for item in items), 2),
        flagged_count=sum(item.flagged_count for item in items),
        cards=items,
        **fx_status(),
    )


@router.post("/credit-card-balances/{account_id}", response_model=CreditCardBalancesOut)
def set_credit_card_balance(
    account_id: int,
    payload: CreditCardBalanceIn,
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    """Record a statement balance typed in by the card's owner (#300): it anchors the
    running balance like an uploaded statement, and History recomputes from its date."""
    card = next((c for c in _credit_cards(db, current_user.id) if int(c["account_id"]) == account_id), None)
    if card is None:
        raise HTTPException(status_code=404, detail="Credit card not found")
    if payload.as_of_date > _app_today():
        raise HTTPException(status_code=422, detail="The statement date can't be in the future")
    if payload.due_date is not None and payload.due_date < payload.as_of_date:
        raise HTTPException(status_code=422, detail="The due date can't be before the statement date")
    write_card_statement_balance(
        db,
        account_id=account_id,
        import_job_id=None,
        parser_key=None,
        parser_meta={"statement_balances": [
            {"as_of_date": payload.as_of_date.isoformat(), "owed": round(payload.owed, 2), "source": "manual"}
        ]},
    )
    if payload.due_date is not None:
        _write_typed_due(db, account_id, payload.as_of_date, payload.due_date, round(payload.owed, 2), payload.minimum_due)
    db.commit()
    return credit_card_balances(base_currency=base_currency, db=db, current_user=current_user)


def _write_typed_due(
    db: Session, account_id: int, statement_date: date, due_date: date, amount_due: float | None, minimum_due: float | None
) -> None:
    try:
        write_due(
            db,
            account_id=account_id,
            statement_date=statement_date,
            due_date=due_date,
            amount_due=amount_due,
            minimum_due=None if minimum_due is None else round(minimum_due, 2),
            source="manual",
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/credit-card-dues/{account_id}", response_model=CreditCardBalancesOut)
def set_credit_card_due(
    account_id: int,
    payload: CreditCardDueIn,
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    """Record the payment due date a card statement prints, typed in by the card's owner
    (#352, D-94). None of the supported card exports state it, so this is where it comes
    from; the Inbox then reminds before it and until the card's payments cover the statement."""
    card = next((c for c in _credit_cards(db, current_user.id) if int(c["account_id"]) == account_id), None)
    if card is None:
        raise HTTPException(status_code=404, detail="Credit card not found")
    if payload.statement_date > _app_today():
        raise HTTPException(status_code=422, detail="The statement date can't be in the future")
    if payload.due_date < payload.statement_date:
        raise HTTPException(status_code=422, detail="The due date can't be before the statement date")
    _write_typed_due(
        db,
        account_id,
        payload.statement_date,
        payload.due_date,
        None if payload.amount_due is None else round(payload.amount_due, 2),
        payload.minimum_due,
    )
    db.commit()
    return credit_card_balances(base_currency=base_currency, db=db, current_user=current_user)


@router.get("/credit-card-transactions", response_model=CreditCardDetailOut)
def credit_card_transactions(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    start = _parse_month(month)
    end = _month_end(start)

    cards = _credit_cards(db, current_user.id)
    spend = _spend_by_account(db, start, end, base_currency, current_user.id)
    card_items = _credit_card_items(cards, spend, start, base_currency, card_due_states(db, current_user.id, today=_app_today()))

    tx_q = text("""
        SELECT
          t.account_id,
          a.name AS account_name,
          COALESCE(NULLIF(TRIM(cc.card_name), ''), a.name) AS card_name,
          COALESCE(NULLIF(TRIM(cc.issuer), ''), a.platform) AS issuer,
          t.ts,
          t.amount,
          t.type,
          t.currency,
          t.category,
          COALESCE(ct.name, NULLIF(TRIM(t.category), ''), 'Uncategorized') AS resolved_category,
          CASE
            WHEN co.source IS NOT NULL THEN co.source
            WHEN t.category IS NOT NULL
                 AND TRIM(t.category) <> ''
                 AND LOWER(TRIM(t.category)) <> 'uncategorized' THEN 'parser'
            ELSE 'uncategorized'
          END AS category_source,
          t.merchant_counterparty,
          t.notes
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        LEFT JOIN credit_card_accounts cc ON cc.account_id = t.account_id
        LEFT JOIN category_overrides co ON co.transaction_id = t.id
        LEFT JOIN category_taxonomy ct ON ct.id = co.category_id
        WHERE t.ts >= :start AND t.ts < :end
          AND a.account_type = 'CREDIT_CARD'
          AND """
            + account_scope_sql("a")
            + """
        ORDER BY t.ts DESC, t.id DESC
    """)
    tx_rows = _window_rows(db, tx_q, {"current_user_id": current_user.id}, start, end)
    tx_rates = _build_row_rate_map(tx_rows, base_currency)

    transactions: list[CreditCardTransactionItem] = []
    for row in tx_rows:
        converted = _row_base_amount(row, base_currency, tx_rates)
        description = row["merchant_counterparty"] or row["resolved_category"] or row["category"] or "Transaction"
        transactions.append(
            CreditCardTransactionItem(
                account_id=int(row["account_id"]),
                account_name=row["account_name"],
                card_name=row["card_name"],
                issuer=row["issuer"],
                ts=_tx_iso(row["ts"]),
                description=description,
                amount=converted,
                type=row["type"],
                category=row["category"],
                resolved_category=row["resolved_category"],
                category_source=row["category_source"],
                merchant_counterparty=row["merchant_counterparty"],
                notes=row["notes"],
            )
        )

    top_purchases = sorted(
        (tx for tx in transactions if tx.type == "EXPENSE"),
        key=lambda tx: abs(tx.amount),
        reverse=True,
    )[:5]

    recurring_payments = _credit_card_recurring_payments(
        db, current_user.id, month, base_currency, _add_months(start, -(RECURRING_LOOKBACK_MONTHS - 1)), end
    )

    total_spend = sum(item.current_due for item in card_items)
    return CreditCardDetailOut(
        month=month,
        base_currency=base_currency,
        total_spend=total_spend,
        cards=card_items,
        transactions=transactions,
        top_purchases=top_purchases,
        recurring_payments=recurring_payments,
        **fx_status(),
    )


@router.get("/credit-card-analytics", response_model=CreditCardAnalyticsOut)
def credit_card_analytics(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    months: int = Query(12, ge=1, le=24),
    account_id: int | None = Query(None),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    start = _parse_month(month)
    end = _month_end(start)
    prior_start = _add_months(start, -1)
    prior_month = _month_key(prior_start)
    trend_start = _add_months(start, -(months - 1))
    fetch_start = min(trend_start, prior_start)
    recurring_lookback_start = _add_months(start, -(RECURRING_LOOKBACK_MONTHS - 1))

    cards_raw = _credit_cards(db, current_user.id)
    analytics_dues = card_due_states(db, current_user.id, today=_app_today())
    owned_account_ids = {int(c["account_id"]) for c in cards_raw}
    if account_id is not None and account_id not in owned_account_ids:
        # 404 rather than 403 — do not disclose whether the id exists for another user.
        raise HTTPException(status_code=404, detail="Credit card not found")

    rows = _credit_card_analytics_rows(db, fetch_start, end, current_user.id)
    month_rates = _build_row_rate_map(rows, base_currency)

    def base_amount(row) -> float:
        return _row_base_amount(row, base_currency, month_rates)

    def spend_amount(row) -> float:
        # Stored transaction amounts are negative for outflows; spend is reported as a
        # positive magnitude everywhere except the transaction/charge ledger rows, which
        # preserve the original signed amount for consistency with
        # /spending/credit-card-transactions.
        return -base_amount(row)

    def is_outflow(row) -> bool:
        # A positive amount on an EXPENSE/FEE/TAX/INTEREST row is a credit/reversal
        # (e.g. a waived late fee), not spend — excluded from every spend aggregate
        # below, per the "exclude credits and refunds" spend definition. The full
        # ledger still lists these rows for transparency.
        return base_amount(row) < 0

    selected_rows = [r for r in rows if _month_key(r["ts"]) == month]
    prior_rows = [r for r in rows if _month_key(r["ts"]) == prior_month]
    trend_rows = [r for r in rows if trend_start <= _parse_month(_month_key(r["ts"])) < end]

    def in_scope(row) -> bool:
        return account_id is None or int(row["account_id"]) == account_id

    # The card filter rail always reflects every owned card's selected-month spend,
    # independent of the requested account_id scope — only the aggregate/detail fields
    # below are scoped.
    spend_by_account: dict[int, float] = defaultdict(float)
    count_by_account: dict[int, int] = defaultdict(int)
    for row in selected_rows:
        if not is_outflow(row):
            continue
        acct = int(row["account_id"])
        spend_by_account[acct] += spend_amount(row)
        if row["type"] == "EXPENSE":
            count_by_account[acct] += 1

    due_fields = {int(c["account_id"]): _card_due_fields(c, analytics_dues, start) for c in cards_raw}
    card_items = [
        CreditCardAnalyticsCardItem(
            account_id=int(c["account_id"]),
            account_name=c["account_name"],
            card_name=c["card_name"],
            issuer=c["issuer"],
            spend=spend_by_account.get(int(c["account_id"]), 0.0),
            transaction_count=count_by_account.get(int(c["account_id"]), 0),
            available_limit=(float(c["available_limit"]) if c["available_limit"] is not None else None),
            available_limit_as_of=(
                _tx_iso(c["available_limit_as_of"]) if c["available_limit_as_of"] is not None else None
            ),
            statement_day=int(c["statement_day"]),
            due_day=int(c["due_day"]),
            due_date=due_fields[int(c["account_id"])][0],
            due_source=due_fields[int(c["account_id"])][1],
            due_status=due_fields[int(c["account_id"])][2],
        )
        for c in cards_raw
    ]

    scoped_selected = [r for r in selected_rows if in_scope(r)]
    scoped_prior = [r for r in prior_rows if in_scope(r)]
    scoped_selected_outflows = [r for r in scoped_selected if is_outflow(r)]

    total_spend = sum(spend_amount(r) for r in scoped_selected_outflows)
    prior_month_spend = sum(spend_amount(r) for r in scoped_prior if is_outflow(r))
    transaction_count = sum(1 for r in scoped_selected_outflows if r["type"] == "EXPENSE")

    purchase_by_category: dict[str, float] = defaultdict(float)
    purchase_spend = 0.0
    for row in scoped_selected_outflows:
        if row["type"] != "EXPENSE":
            continue
        amount = spend_amount(row)
        purchase_spend += amount
        category = row["resolved_category"] or "Uncategorized"
        purchase_by_category[category] += amount
    categories = _sorted_breakdown_items(purchase_by_category, purchase_spend)

    charge_rows = [r for r in scoped_selected_outflows if r["type"] in ("FEE", "TAX", "INTEREST")]
    charges = [_cc_transaction_item(r, base_amount(r)) for r in charge_rows]
    charge_total = sum(spend_amount(r) for r in charge_rows)

    # The transaction ledger itself stays unfiltered — credits/reversals still need to
    # be visible there for a complete audit trail, even though they're excluded above.
    transactions = [_cc_transaction_item(r, base_amount(r)) for r in scoped_selected]

    trend_totals: dict[str, float] = defaultdict(float)
    for row in trend_rows:
        if not in_scope(row) or not is_outflow(row):
            continue
        trend_totals[_month_key(row["ts"])] += spend_amount(row)
    trend: list[CreditCardAnalyticsTrendPoint] = []
    for offset in range(months):
        point_month = _month_key(_add_months(trend_start, offset))
        trend.append(CreditCardAnalyticsTrendPoint(month=point_month, spend=trend_totals.get(point_month, 0.0)))

    recurring_payments = _credit_card_recurring_payments(
        db, current_user.id, month, base_currency, recurring_lookback_start, end, account_id=account_id
    )

    return CreditCardAnalyticsOut(
        month=month,
        base_currency=base_currency,
        months=months,
        account_id=account_id,
        total_spend=total_spend,
        transaction_count=transaction_count,
        purchase_spend=purchase_spend,
        prior_month=prior_month,
        prior_month_spend=prior_month_spend,
        cards=card_items,
        charges=charges,
        charge_total=charge_total,
        categories=categories,
        trend=trend,
        transactions=transactions,
        recurring_payments=recurring_payments,
        **fx_status(),
    )
