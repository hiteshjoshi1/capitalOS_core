"""Income (#267): dividends plus interest, trailing 12 months and year to date vs a year earlier."""
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.portfolio.income import add_months, income_summary, window_end


def _seed(db_engine):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO accounts (id, name, platform, account_type, currency, country, user_id) VALUES
                (701, 'Synthetic Broker', 'IBKR', 'BROKER', 'USD', 'US', 1),
                (702, 'Synthetic Bank', 'OCBC', 'BANK', 'USD', 'SG', 1),
                (703, 'Synthetic Card', 'DBS', 'CREDIT_CARD', 'USD', 'SG', 1)
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO transactions
                  (id, ts, account_id, amount, type, currency, category, merchant_counterparty, source)
                VALUES
                  -- the 12 months before (Jul 2024 - Jun 2025)
                  (801, '2024-09-15T04:00:00+00:00', 701, 100, 'INCOME', 'USD', 'Brokerage::Dividend', 'AAA DIVIDEND', 'TEST'),
                  (802, '2025-03-15T04:00:00+00:00', 702, 20, 'INCOME', 'USD', 'Income::Interest', 'INTEREST CREDIT', 'TEST'),
                  -- the last 12 months (Jul 2025 - Jun 2026)
                  (811, '2025-08-15T04:00:00+00:00', 701, 150, 'INCOME', 'USD', 'Brokerage::Dividend', 'AAA DIVIDEND', 'TEST'),
                  (812, '2025-08-15T04:00:00+00:00', 701, -15, 'TAX', 'USD', 'Brokerage::Tax', 'AAA DIVIDEND TAX', 'TEST'),
                  (813, '2026-02-15T04:00:00+00:00', 702, 30, 'INCOME', 'USD', 'Income::Interest', 'BONUS INTEREST', 'TEST'),
                  (814, '2026-06-10T04:00:00+00:00', 701, 50, 'INCOME', 'USD', 'Brokerage::Dividend', 'AAA DIVIDEND', 'TEST'),
                  -- not income: card interest charged, a salary, a dividend after June
                  (821, '2026-03-05T04:00:00+00:00', 703, -40, 'INTEREST', 'USD', 'CreditCard::Interest', 'FINANCE CHARGE', 'TEST'),
                  (822, '2026-03-25T04:00:00+00:00', 702, 5000, 'INCOME', 'USD', 'Income::Salary', 'SALARY', 'TEST'),
                  (823, '2026-07-02T04:00:00+00:00', 701, 999, 'INCOME', 'USD', 'Brokerage::Dividend', 'AAA DIVIDEND', 'TEST')
                """
            )
        )


def test_income_summary_trailing_12_and_ytd_vs_a_year_earlier(client, db_engine):
    _seed(db_engine)
    resp = client.get("/income/summary?month=2026-06&base_currency=USD")
    assert resp.status_code == 200
    data = resp.json()

    assert data["as_of"] == "2026-06-30"
    assert data["partial_month"] is False
    trailing = data["trailing_12"]
    assert (trailing["from_date"], trailing["to_date"]) == ("2025-07-01", "2026-06-30")
    # Dividends net of withholding (150 - 15 + 50); interest is the bank's credit only.
    assert trailing["dividends"] == pytest.approx(185.0)
    assert trailing["interest"] == pytest.approx(30.0)
    assert trailing["total"] == pytest.approx(215.0)
    prior = data["prior_12"]
    assert (prior["from_date"], prior["to_date"]) == ("2024-07-01", "2025-06-30")
    assert prior["total"] == pytest.approx(120.0)
    assert data["trailing_12_change_pct"] == pytest.approx(95.0 / 120.0)

    ytd, prior_ytd = data["ytd"], data["prior_ytd"]
    assert (ytd["from_date"], ytd["to_date"]) == ("2026-01-01", "2026-06-30")
    assert ytd["total"] == pytest.approx(80.0)  # Feb interest 30 + Jun dividend 50
    assert (prior_ytd["from_date"], prior_ytd["to_date"]) == ("2025-01-01", "2025-06-30")
    assert prior_ytd["total"] == pytest.approx(20.0)
    assert data["ytd_change_pct"] == pytest.approx(3.0)

    months = data["months"]
    assert [m["month"] for m in months][:1] == ["2025-07"] and months[-1]["month"] == "2026-06"
    assert len(months) == 12
    by_month = {m["month"]: m for m in months}
    assert by_month["2025-08"]["dividends"] == pytest.approx(135.0)
    assert by_month["2026-02"]["interest"] == pytest.approx(30.0)
    assert by_month["2026-03"]["total"] == pytest.approx(0.0)  # card interest and salary aren't income


def test_income_summary_no_prior_year_has_no_change(client, db_engine):
    resp = client.get("/income/summary?month=2026-06&base_currency=USD")
    assert resp.status_code == 200
    data = resp.json()
    assert data["trailing_12"]["total"] == 0
    assert data["trailing_12_change_pct"] is None
    assert data["ytd_change_pct"] is None


def test_income_summary_rejects_a_bad_month(client):
    assert client.get("/income/summary?month=June").status_code == 422


def test_current_month_compares_like_for_like_to_date(db_engine):
    _seed(db_engine)
    with Session(db_engine) as db:
        data = income_summary(db, 1, "2026-07", "USD", today=date(2026, 7, 5))
    assert data["partial_month"] is True
    assert data["as_of"] == "2026-07-05"
    # Trailing 12 = 6 Jul 2025 .. 5 Jul 2026: Jul 2 dividend in, Aug-Jun as before.
    assert (data["trailing_12"]["from_date"], data["trailing_12"]["to_date"]) == ("2025-07-06", "2026-07-05")
    assert data["trailing_12"]["total"] == pytest.approx(215.0 + 999.0)
    assert (data["prior_ytd"]["from_date"], data["prior_ytd"]["to_date"]) == ("2025-01-01", "2025-07-05")
    assert data["months"][-1] == {"month": "2026-07", "dividends": pytest.approx(999.0), "interest": 0.0, "total": pytest.approx(999.0)}


def test_window_helpers():
    assert window_end("2026-06", date(2026, 11, 7)) == date(2026, 7, 1)
    assert window_end("2026-12", date(2027, 3, 1)) == date(2027, 1, 1)
    assert window_end("2026-11", date(2026, 11, 7)) == date(2026, 11, 8)
    assert add_months(date(2026, 3, 31), -1) == date(2026, 2, 28)
    assert add_months(date(2026, 1, 15), -12) == date(2025, 1, 15)
    assert add_months(date(2026, 12, 1), 1) == date(2027, 1, 1)
