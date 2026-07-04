from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import CurrentUser, account_scope_sql, require_current_user
from app.db.session import get_db
from app.fx import get_rates
from app.routers.dashboard import _anchor_ts, _effective_as_of, _networth_components
from app.schemas.spending import (
    CategoryAmount,
    CashFlowAnalyticsOut,
    CashFlowBreakdownItem,
    CashFlowCategoryDeltaItem,
    CashFlowDiagnosticAnswer,
    CashFlowDetailOut,
    CashFlowDetailSection,
    CashFlowMerchantItem,
    CashFlowTrendPoint,
    CashFlowTransactionItem,
    CashFlowWaterfallOut,
    CreditCardSummaryOut,
    CreditCardItem,
    CreditCardDetailOut,
    CreditCardTransactionItem,
    CreditCardRecurringPaymentItem,
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
        raise HTTPException(status_code=400, detail="Invalid month format. Use YYYY-MM, e.g. 2026-02")


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
    if isinstance(value, datetime):
        return value.strftime("%Y-%m")
    as_text = str(value)
    return as_text[:7]


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
          t.notes
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
    return db.execute(cash_flow_q, {"start": start, "end": end, "current_user_id": current_user_id}).mappings().all()


def _is_transfer_resolved_category(row) -> bool:
    resolved_code = str(row.get("resolved_category_code") or "").strip().lower()
    parent_code = str(row.get("resolved_parent_category_code") or "").strip().lower()
    return resolved_code == "transfer" or parent_code == "transfer"


def _is_explicit_source_transfer(row) -> bool:
    raw_category = str(row.get("raw_category") or "").strip().lower()
    if raw_category in EXPLICIT_TRANSFER_RAW_CATEGORIES:
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


def _build_month_rate_map(rows, base_currency: str) -> dict[str, dict[str, float]]:
    currencies_by_month: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        month_key = _month_key(row["ts"])
        currency = (row["currency"] or base_currency).upper()
        currencies_by_month[month_key].add(currency)

    return {
        month_key: get_rates(_parse_month(month_key), base_currency, currencies)
        for month_key, currencies in currencies_by_month.items()
    }


def _row_base_amount(row, base_currency: str, month_rates: dict[str, dict[str, float]]) -> float:
    month_key = _month_key(row["ts"])
    currency = (row["currency"] or base_currency).upper()
    rates = month_rates.get(month_key, {})
    return float(row["amount"]) * rates.get(currency, 1.0)


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


def _is_stable_recurring_charge(monthly_amounts: dict[str, float]) -> bool:
    amounts = sorted(round(abs(amount), 2) for amount in monthly_amounts.values() if amount > 0)
    if len(amounts) < 3:
        return False
    median = amounts[len(amounts) // 2]
    tolerance = max(2.0, median * 0.10)
    return all(abs(amount - median) <= tolerance for amount in amounts)


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
    month_rates = _build_month_rate_map(rows, base_currency)
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
    current_month_rates = _build_month_rate_map(current_rows, base_currency)
    prior_month = _month_key(_add_months(_parse_month(month), -1))
    prior_rows = [row for row in lookback_rows if _month_key(row["ts"]) == prior_month]
    prior_month_rates = _build_month_rate_map(prior_rows, base_currency)
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
    ending_cash = _networth_components(db, anchor, base_currency, current_user_id)["cash"]
    starting_cash = _networth_components(db, prior_anchor, base_currency, current_user_id)["cash"]
    transfers_and_funding = 0.0
    investment_and_fx_effects = None
    other_cash_movements = None
    if snapshot_start_as_of is not None and snapshot_end_as_of is not None:
        reconciliation_rows = [
            row
            for row in lookback_rows
            if snapshot_start_as_of < _row_ts(row["ts"]) <= snapshot_end_as_of
        ]
    else:
        reconciliation_rows = current_rows
    reconciliation_rates = _build_month_rate_map(reconciliation_rows, base_currency)
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
    availability_message = None
    if not boundary_exact:
        availability_message = (
            f"Cash reconciliation needs exact cash snapshots on {prior_anchor.date().isoformat()} and {anchor.date().isoformat()}. "
            f"Available snapshots are {(snapshot_start_as_of.date().isoformat() if snapshot_start_as_of is not None else 'missing')} "
            f"and {(snapshot_end_as_of.date().isoformat() if snapshot_end_as_of is not None else 'missing')}."
        )

    top_outflow_merchants = sorted(
        merchant_totals.items(),
        key=lambda entry: (-entry[1], entry[0].lower()),
    )[:5]

    deterioration_items: list[CashFlowCategoryDeltaItem] = []
    for label in set(category_impacts_current) | set(category_impacts_prior):
        current_value = category_impacts_current.get(label, 0.0)
        prior_value = category_impacts_prior.get(label, 0.0)
        delta = current_value - prior_value
        if delta >= 0:
            continue
        deterioration_items.append(
            CashFlowCategoryDeltaItem(
                label=label,
                current_amount=current_value,
                prior_amount=prior_value,
                delta_amount=delta,
                delta_percent=(delta / prior_value) if prior_value not in (0, 0.0) else None,
                direction="deteriorated",
            )
        )
    deterioration_items.sort(key=lambda item: (item.delta_amount, item.label.lower()))

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
            ending_cash=ending_cash,
        ),
        answers=answers,
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
          COALESCE(cc.statement_day, 1) AS statement_day,
          COALESCE(cc.due_day, 1) AS due_day
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
    spend_rows = db.execute(
        spend_q,
        {"start": start, "end": end, "current_user_id": current_user_id},
    ).mappings().all()
    currencies = {r["currency"] for r in spend_rows if r["currency"]}
    rates = get_rates(start, base_currency, currencies)
    spend: dict[int, float] = {}
    for row in spend_rows:
        cur = (row["currency"] or base_currency).upper()
        converted = float(row["amount"]) * rates.get(cur, 1.0)
        account_id = int(row["account_id"])
        spend[account_id] = spend.get(account_id, 0.0) + (-converted)
    return spend


def _credit_card_items(
    cards,
    spend_by_account: dict[int, float],
    start: datetime,
    base_currency: str,
) -> list[CreditCardItem]:
    account_currencies = {(c["account_currency"] or base_currency).upper() for c in cards}
    account_rates = get_rates(start, base_currency, account_currencies)
    items: list[CreditCardItem] = []
    for card in cards:
        account_currency = (card["account_currency"] or base_currency).upper()
        rate = account_rates.get(account_currency, 1.0)
        credit_limit = float(card["credit_limit"]) * rate
        current_due = spend_by_account.get(int(card["account_id"]), 0.0)
        utilization = (current_due / credit_limit) if credit_limit > 0 else None
        due_date = _clamp_day(start, int(card["due_day"])).date().isoformat()
        items.append(
            CreditCardItem(
                account_id=int(card["account_id"]),
                account_name=card["account_name"],
                card_name=card["card_name"],
                issuer=card["issuer"],
                credit_limit=credit_limit,
                statement_day=int(card["statement_day"]),
                due_day=int(card["due_day"]),
                due_date=due_date,
                current_due=current_due,
                utilization=utilization,
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
    currencies = {r["currency"] for r in rows if r["currency"]}
    rates = get_rates(start, base_currency, currencies)

    income_total = 0.0
    expense_total = 0.0
    income_categories: dict[str, float] = {}
    expense_categories: dict[str, float] = {}
    for r in rows:
        cur = (r["currency"] or base_currency).upper()
        amount = float(r["amount"]) * rates.get(cur, 1.0)
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
    rates = _build_month_rate_map(rows, base_currency).get(month, {})

    income_total = 0.0
    expense_total = 0.0
    income_transactions: list[CashFlowTransactionItem] = []
    expense_transactions: list[CashFlowTransactionItem] = []

    for row in rows:
        currency = (row["currency"] or base_currency).upper()
        base_amount = float(row["amount"]) * rates.get(currency, 1.0)
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
        analytics=_analytics_for_month(
            current_rows=rows,
            lookback_rows=lookback_rows,
            month=month,
            base_currency=base_currency,
            current_user_id=current_user.id,
            db=db,
            income_total=income_total,
            expense_total=expense_total,
            net=net,
        ),
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
    items = _credit_card_items(cards, spend, start, base_currency)

    total_spend = sum(i.current_due for i in items)
    return CreditCardSummaryOut(
        month=month,
        base_currency=base_currency,
        total_spend=total_spend,
        cards=items,
    )


@router.get("/credit-card-transactions", response_model=CreditCardDetailOut)
def credit_card_transactions(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    start = _parse_month(month)
    end = _month_end(start)
    lookback_start = _add_months(start, -2)

    cards = _credit_cards(db, current_user.id)
    spend = _spend_by_account(db, start, end, base_currency, current_user.id)
    card_items = _credit_card_items(cards, spend, start, base_currency)

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
    tx_rows = db.execute(
        tx_q,
        {"start": start, "end": end, "current_user_id": current_user.id},
    ).mappings().all()
    tx_currencies = {r["currency"] for r in tx_rows if r["currency"]}
    tx_rates = get_rates(start, base_currency, tx_currencies)

    transactions: list[CreditCardTransactionItem] = []
    for row in tx_rows:
        cur = (row["currency"] or base_currency).upper()
        converted = float(row["amount"]) * tx_rates.get(cur, 1.0)
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
          AND COALESCE(TRIM(t.merchant_counterparty), '') <> ''
        ORDER BY t.ts DESC, t.id DESC
    """)
    recurring_rows = db.execute(
        recurring_q,
        {"lookback_start": lookback_start, "end": end, "current_user_id": current_user.id},
    ).mappings().all()
    recurring_currencies = {r["currency"] for r in recurring_rows if r["currency"]}
    recurring_rates = get_rates(start, base_currency, recurring_currencies)

    recurring_index: dict[tuple[int, str], dict] = {}
    for row in recurring_rows:
        merchant = str(row["merchant_counterparty"]).strip()
        key = (int(row["account_id"]), merchant)
        cur = (row["currency"] or base_currency).upper()
        converted = float(row["amount"]) * recurring_rates.get(cur, 1.0)
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
                "current_month_amount": 0.0,
            },
        )
        month_key = _month_key(row["ts"])
        amount = -converted
        record["months"].add(month_key)
        record["monthly_amounts"][month_key] += amount
        if month_key == month:
            record["current_month_amount"] += amount

    recurring_payments: list[CreditCardRecurringPaymentItem] = []
    for record in recurring_index.values():
        months_present = len(record["months"])
        current_month_amount = float(record["current_month_amount"])
        if current_month_amount <= 0 or not _is_stable_recurring_charge(record["monthly_amounts"]):
            continue
        recurring_payments.append(
            CreditCardRecurringPaymentItem(
                account_id=record["account_id"],
                account_name=record["account_name"],
                card_name=record["card_name"],
                issuer=record["issuer"],
                merchant_counterparty=record["merchant_counterparty"],
                months_present=months_present,
                current_month_amount=current_month_amount,
            )
        )

    recurring_payments.sort(
        key=lambda item: (item.current_month_amount, item.merchant_counterparty.lower()),
        reverse=True,
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
    )
