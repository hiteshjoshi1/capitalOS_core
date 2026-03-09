from fastapi.testclient import TestClient
from sqlalchemy import text


def test_spending_summary(client: TestClient, seed_spending_data):
    resp = client.get("/spending/summary?month=2026-02&base_currency=SGD")
    assert resp.status_code == 200
    data = resp.json()

    assert data["income_total"] == 12480.0
    assert data["expense_total"] == 8710.0
    assert data["net"] == 3770.0
    assert data["savings_rate"] == 3770.0 / 12480.0

    income_categories = {c["category"]: c["amount"] for c in data["income_categories"]}
    assert income_categories["Salary"] == 12000.0
    assert income_categories["Dividends"] == 480.0

    expense_categories = {c["category"]: c["amount"] for c in data["expense_categories"]}
    assert expense_categories["Rent"] == 3200.0
    assert expense_categories["Groceries"] == 1210.0


def test_credit_card_summary(client: TestClient, seed_spending_data):
    resp = client.get("/spending/credit-cards?month=2026-02&base_currency=SGD")
    assert resp.status_code == 200
    data = resp.json()

    assert data["total_spend"] == 2990.0
    assert len(data["cards"]) == 1
    card = data["cards"][0]
    assert card["card_name"] == "DBS Altitude"
    assert card["current_due"] == 2990.0
    assert card["credit_limit"] == 20000.0
    assert card["utilization"] == 2990.0 / 20000.0


def test_credit_card_transactions_detail(client: TestClient, seed_spending_data):
    resp = client.get("/spending/credit-card-transactions?month=2026-02&base_currency=SGD")
    assert resp.status_code == 200
    data = resp.json()

    assert data["month"] == "2026-02"
    assert data["base_currency"] == "SGD"
    assert data["total_spend"] == 2990.0
    assert len(data["cards"]) == 1
    assert data["cards"][0]["card_name"] == "DBS Altitude"

    assert len(data["transactions"]) == 2
    first_tx = data["transactions"][0]
    assert first_tx["description"] == "Netflix"
    assert first_tx["amount"] == -1210.0
    assert first_tx["type"] == "EXPENSE"
    assert first_tx["category"] == "Groceries"

    assert [abs(item["amount"]) for item in data["top_purchases"]] == [1780.0, 1210.0]
    assert len(data["recurring_payments"]) == 1
    recurring = data["recurring_payments"][0]
    assert recurring["merchant_counterparty"] == "Netflix"
    assert recurring["months_present"] == 3
    assert recurring["current_month_amount"] == 1210.0


def test_credit_card_endpoints_include_credit_card_accounts_without_metadata(client: TestClient, db_engine):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country) VALUES "
                "(500, 'Citi CC', 'CITI', 'CREDIT_CARD', 'SGD', 'SG')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO transactions (id, ts, account_id, amount, type, currency, category, merchant_counterparty, notes) VALUES "
                "(1, '2026-03-06 00:00:00+00:00', 500, -250, 'EXPENSE', 'SGD', 'CreditCard::Purchase', 'SHENG SIONG', NULL), "
                "(2, '2026-03-04 00:00:00+00:00', 500, -100, 'FEE', 'SGD', 'CreditCard::Fee', 'LATE CHARGE FEE', NULL)"
            )
        )

    summary_resp = client.get("/spending/credit-cards?month=2026-03&base_currency=SGD")
    assert summary_resp.status_code == 200
    summary = summary_resp.json()
    assert summary["total_spend"] == 350.0
    assert len(summary["cards"]) == 1
    assert summary["cards"][0]["account_name"] == "Citi CC"
    assert summary["cards"][0]["card_name"] == "Citi CC"
    assert summary["cards"][0]["issuer"] == "CITI"

    detail_resp = client.get("/spending/credit-card-transactions?month=2026-03&base_currency=SGD")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["total_spend"] == 350.0
    assert len(detail["transactions"]) == 2
    assert detail["transactions"][0]["card_name"] == "Citi CC"
    assert detail["transactions"][0]["issuer"] == "CITI"
