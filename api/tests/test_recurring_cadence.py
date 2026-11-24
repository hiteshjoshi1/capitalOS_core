"""A card charge is a real repeat (#266): detect_recurring_cadence."""
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.routers.spending import detect_recurring_cadence

MONTH = "2026-06"


def test_a_monthly_subscription_is_recurring():
    charges = {"2026-04": [18.0], "2026-05": [18.0], "2026-06": [18.0]}
    assert detect_recurring_cadence(charges, MONTH) == "monthly"


def test_small_price_changes_stay_recurring():
    # Within max(2, 10%) of the median: a price rise or an FX wobble.
    charges = {"2026-03": [15.98], "2026-04": [17.98], "2026-05": [17.98], "2026-06": [18.5]}
    assert detect_recurring_cadence(charges, MONTH) == "monthly"


def test_one_missed_month_is_allowed_two_are_not():
    assert detect_recurring_cadence({"2026-02": [9.0], "2026-04": [9.0], "2026-05": [9.0], "2026-06": [9.0]}, MONTH) == "monthly"
    assert detect_recurring_cadence({"2026-01": [9.0], "2026-03": [9.0], "2026-05": [9.0], "2026-06": [9.0]}, MONTH) is None
    assert detect_recurring_cadence({"2026-01": [9.0], "2026-04": [9.0], "2026-06": [9.0]}, MONTH) is None


def test_fewer_than_three_months_or_not_this_month_is_not_recurring():
    assert detect_recurring_cadence({"2026-05": [18.0], "2026-06": [18.0]}, MONTH) is None
    assert detect_recurring_cadence({"2026-03": [18.0], "2026-04": [18.0], "2026-05": [18.0]}, MONTH) is None


def test_shopping_with_several_charges_a_month_is_not_recurring():
    # Same shop, similar monthly totals, but several purchases a month: shopping.
    charges = {"2026-04": [40.0, 60.0], "2026-05": [100.0], "2026-06": [55.0, 45.0]}
    assert detect_recurring_cadence(charges, MONTH) is None


def test_varying_amounts_are_not_recurring():
    charges = {"2026-04": [90.0], "2026-05": [130.0], "2026-06": [65.0]}
    assert detect_recurring_cadence(charges, MONTH) is None


def test_refunds_and_zero_amounts_are_ignored():
    charges = {"2026-04": [18.0], "2026-05": [18.0, 0.0], "2026-06": [18.0]}
    assert detect_recurring_cadence(charges, MONTH) == "monthly"


def test_analytics_reports_cadence_and_typical_amount_and_skips_shopping(client: TestClient, db_engine):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, user_id) VALUES "
                "(26601, 'Synthetic Card', 'UOB', 'CREDIT_CARD', 'SGD', 'SG', 1)"
            )
        )
        rows = []
        tid = 2660100
        for m in ("2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"):
            tid += 1
            rows.append(f"({tid}, '{m}-08 00:00:00+00:00', 26601, -18, 'EXPENSE', 'SGD', 'Subscription', 'Streamly', NULL)")
            # Two similar purchases every month at the same shop: not a subscription.
            tid += 1
            rows.append(f"({tid}, '{m}-12 00:00:00+00:00', 26601, -50, 'EXPENSE', 'SGD', 'Shopping', 'Mall Shop', NULL)")
            tid += 1
            rows.append(f"({tid}, '{m}-20 00:00:00+00:00', 26601, -50, 'EXPENSE', 'SGD', 'Shopping', 'Mall Shop', NULL)")
        conn.execute(
            text(
                "INSERT INTO transactions (id, ts, account_id, amount, type, currency, category, merchant_counterparty, notes) VALUES "
                + ", ".join(rows)
            )
        )

    resp = client.get("/spending/credit-card-analytics?month=2026-06&base_currency=SGD")
    assert resp.status_code == 200
    recurring = {r["merchant_counterparty"]: r for r in resp.json()["recurring_payments"]}
    assert set(recurring) == {"Streamly"}
    assert recurring["Streamly"]["cadence"] == "monthly"
    assert recurring["Streamly"]["typical_amount"] == 18.0
    # The six-month window (#266): every month of it counts.
    assert recurring["Streamly"]["months_present"] == 6


def _row(month: str, merchant: str, amount: float, category: str = "Shopping", day: int = 5) -> dict:
    return {
        "ts": f"{month}-{day:02d}T10:00:00+00:00", "amount": amount, "type": "EXPENSE" if amount < 0 else "INCOME",
        "merchant_counterparty": merchant, "raw_category": category, "resolved_category": category,
        "resolved_category_code": "", "resolved_parent_category_code": "", "notes": None,
    }


def test_cash_flow_recurring_needs_a_regular_amount_and_interval_not_just_the_merchant():
    """#473 (V20): Cash Flow's "Recurring vs. one-off" called a counterparty recurring once
    it showed up in two months, so a supermarket, a shop or a hotel seen twice made every
    outflow "recurring". Now it takes the Cards' rule: once a month, every month, a
    stable amount; or a category that names a recurring kind (rent, insurance, ...)."""
    from app.routers.spending import _is_recurring_row, _merchant_charges_by_month

    months = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]
    rows = []
    for i, m in enumerate(months):
        rows.append(_row(m, "Streaming Co", -18.0))  # a subscription
        rows.append(_row(m, "Supermarket", -(80.0 + 35 * i)))  # every month, amounts vary
        rows.append(_row(m, "Supermarket", -40.0, day=20))
        rows.append(_row(m, "Gym", -120.0 + (i % 2) * 4))  # within 10%
    rows.append(_row("2026-03", "Boutique", -900.0))
    rows.append(_row("2026-06", "Boutique", -450.0))  # the same shop twice: still a one-off
    rows.append(_row("2026-06", "Resort", -2_400.0))
    rows.append(_row("2026-06", "Landlord Pte Ltd", -3_000.0, category="Rent"))  # first month, by category
    charges = _merchant_charges_by_month(rows)
    june = {r["merchant_counterparty"]: _is_recurring_row(r, charges, "2026-06") for r in rows if r["ts"].startswith("2026-06")}
    assert june == {
        "Streaming Co": True, "Gym": True, "Landlord Pte Ltd": True,
        "Supermarket": False, "Boutique": False, "Resort": False,
    }
    # Two months of a subscription aren't a pattern yet (three are needed, as on Cards). The
    # window ends at the month judged, as cash_flow_detail reads it.
    early = _merchant_charges_by_month([r for r in rows if r["ts"] < "2026-03"])
    assert _is_recurring_row(_row("2026-02", "Streaming Co", -18.0), early, "2026-02") is False


def test_cash_flow_detail_splits_recurring_by_the_regular_rule(client: TestClient, db_engine):
    """The endpoint end to end, on a synthetic user's bank account (#473)."""
    from tests.auth_helpers import ensure_user
    from tests.valuation_household import as_user

    ensure_user(db_engine, 1)
    rows = []
    for i, m in enumerate(("2025-04", "2025-05", "2025-06")):
        rows.append((f"{m}-03 09:00:00+00:00", -25.0, "Entertainment", "Synthetic Music"))  # regular
        rows.append((f"{m}-12 09:00:00+00:00", -(150.0 + 95 * i), "Groceries", "Synthetic Grocer"))  # varies
    rows.append(("2025-06-20 09:00:00+00:00", -500.0, "Shopping", "Synthetic Boutique"))
    with db_engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO accounts (id, name, platform, account_type, currency, country, user_id) "
            "VALUES (9811, 'Synthetic Bank', 'SYNTH', 'BANK', 'SGD', 'SG', 1)"
        ))
        conn.execute(
            text(
                "INSERT INTO transactions (ts, account_id, amount, type, currency, category, merchant_counterparty) "
                "VALUES (:ts, 9811, :amt, 'EXPENSE', 'SGD', :cat, :m)"
            ),
            [{"ts": ts, "amt": amt, "cat": cat, "m": m} for ts, amt, cat, m in rows],
        )
    as_user(client, 1)
    resp = client.get("/spending/cash-flow-detail?month=2025-06&base_currency=SGD")
    assert resp.status_code == 200, resp.text
    split = {item["label"]: item["amount"] for item in resp.json()["analytics"]["outflow_recurring_split"]}
    # The music subscription is recurring; the groceries (every month, amounts vary) and
    # the boutique are not. Before #473 the groceries counted as recurring too.
    assert split == {"Recurring": 25.0, "One-off": 340.0 + 500.0}
