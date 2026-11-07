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
