"""Expected dividends when no yield is stored (#409, U16, D-113): a held company is projected
from what it actually paid in the twelve months to the period's end, and the response says
which method each company used. Synthetic data only."""
from sqlalchemy import text

from tests.canonical_test_helpers import seed_canonical_position_snapshot_for_test
from tests.test_dividends import _seed_dividend_data


def _overview(client, to_month="2026-03"):
    resp = client.get(f"/dividends/expected/overview?from_month={to_month}&to_month={to_month}&base_currency=USD")
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_no_yield_projects_from_last_twelve_months_payments(client, db_engine):
    # AAPL held (100 shares), no market_dividend_yields row; it paid 100 (Jan) + 80 (Feb) gross.
    _seed_dividend_data(db_engine)
    payload = _overview(client)
    assert payload["companies_by_yield"] == 0
    assert payload["companies_by_past_payments"] == 1
    company = payload["companies"][0]
    assert company["symbol"] == "AAPL"
    assert company["method"] == "past_payments"
    assert company["yield_pct"] is None
    assert round(company["yearly_dividend"], 2) == 180.0
    assert round(company["quarterly_dividend"], 2) == 45.0
    assert round(payload["yearly"]["gross"], 2) == 180.0


def test_payments_older_than_twelve_months_are_not_projected(client, db_engine):
    _seed_dividend_data(db_engine)
    # A year after the last payment (Feb 2026): nothing paid in Mar 2026–Feb 2027.
    payload = _overview(client, to_month="2027-02")
    assert payload["companies_by_past_payments"] == 0
    assert payload["companies"] == []
    assert payload["yearly"]["gross"] == 0


def test_stored_yield_wins_and_both_methods_are_counted(client, db_engine):
    _seed_dividend_data(db_engine)  # AAPL: no yield, past payments
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) "
                "VALUES (902, 'MSFT', 'Microsoft', 'STOCK', 'USD', 'US')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO market_dividend_yields "
                "(asset_id, as_of_date, yield_rate, annual_dividend_per_share, price, currency, source, exchange_code, provider_symbol) "
                "VALUES (902, '2026-03-31', 0.01, 4, 400, 'USD', 'yfinance_dividend', 'US', 'MSFT')"
            )
        )
    seed_canonical_position_snapshot_for_test(
        db_engine,
        account_id=501,
        asset_id=902,
        as_of="2026-02-06",
        quantity=10,
        market_value_base=4000,
        market_price=400,
        cost_basis_base=4000,
        currency="USD",
        platform_code="IBKR",
    )
    payload = _overview(client)
    by_symbol = {c["symbol"]: c for c in payload["companies"]}
    assert by_symbol["MSFT"]["method"] == "yield"
    assert round(by_symbol["MSFT"]["yearly_dividend"], 2) == 40.0  # 10 x 400 x 1 %
    assert by_symbol["AAPL"]["method"] == "past_payments"
    assert (payload["companies_by_yield"], payload["companies_by_past_payments"]) == (1, 1)
    assert round(payload["yearly"]["gross"], 2) == 220.0
