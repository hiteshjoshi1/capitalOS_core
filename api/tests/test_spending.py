from fastapi.testclient import TestClient


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
