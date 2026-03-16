from fastapi.testclient import TestClient
from sqlalchemy import text


def _seed_category_reference_data(db_engine) -> dict[str, int]:
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO category_taxonomy (id, code, name, parent_id, display_order) VALUES
                  (100, 'income', 'Income', NULL, 10),
                  (101, 'income_salary', 'Salary', 100, 11),
                  (102, 'income_dividends', 'Dividends', 100, 12),
                  (110, 'food_dining', 'Food & Dining', NULL, 30),
                  (111, 'food_dining_restaurants', 'Dining Out', 110, 31),
                  (120, 'transportation', 'Transportation', NULL, 40),
                  (121, 'transportation_rideshare', 'Rideshare', 120, 41),
                  (130, 'financial', 'Financial', NULL, 80),
                  (131, 'financial_investment_fees', 'Investment Fees', 130, 81),
                  (140, 'taxes', 'Taxes', NULL, 90),
                  (141, 'taxes_withholding', 'Withholding Tax', 140, 91),
                  (150, 'transfer', 'Transfer', NULL, 100),
                  (151, 'transfer_internal', 'Internal Transfer', 150, 101),
                  (152, 'transfer_credit_card_payment', 'Credit Card Payment', 150, 102),
                  (153, 'transfer_brokerage', 'Brokerage Transfer', 150, 103),
                  (160, 'uncategorized', 'Uncategorized', NULL, 110)
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO category_rules (
                  id,
                  name,
                  priority,
                  source_category_pattern,
                  target_category_id,
                  active
                ) VALUES
                  (1000, 'Bridge Brokerage Dividends', 10, 'Brokerage::Dividend', 102, 1),
                  (1001, 'Bridge Brokerage Fees', 20, 'Brokerage::Fee', 131, 1),
                  (1002, 'Bridge Brokerage Tax', 30, 'Brokerage::Tax', 141, 1),
                  (1003, 'Bridge Bank Transfer', 40, 'Bank::Transfer', 151, 1),
                  (1004, 'Bridge Credit Card Payment', 50, 'CreditCard::Payment', 152, 1),
                  (1005, 'Bridge Brokerage Transfer', 60, 'Brokerage::Transfer', 153, 1)
                """
            )
        )
    return {
        "salary": 101,
        "dividends": 102,
        "rideshare": 121,
        "internal_transfer": 151,
        "uncategorized": 160,
    }


def test_categories_and_rules_crud(client: TestClient, db_engine):
    category_ids = _seed_category_reference_data(db_engine)

    categories_resp = client.get("/categories")
    assert categories_resp.status_code == 200
    categories = categories_resp.json()
    assert any(item["code"] == "income" and item["parent_id"] is None for item in categories)
    assert any(
        item["code"] == "income_dividends" and item["parent_id"] == 100
        for item in categories
    )

    rules_resp = client.get("/categories/rules")
    assert rules_resp.status_code == 200
    rules = rules_resp.json()
    assert [rule["name"] for rule in rules[:2]] == [
        "Bridge Brokerage Dividends",
        "Bridge Brokerage Fees",
    ]

    create_resp = client.post(
        "/categories/rules",
        json={
            "name": "Grab rides",
            "priority": 15,
            "merchant_pattern": "%GRAB%",
            "target_category_id": category_ids["rideshare"],
        },
    )
    assert create_resp.status_code == 200
    created_rule = create_resp.json()
    assert created_rule["target_category_name"] == "Rideshare"
    assert created_rule["merchant_pattern"] == "%GRAB%"

    rule_id = created_rule["id"]
    update_resp = client.put(
        f"/categories/rules/{rule_id}",
        json={"priority": 12, "description_pattern": "%airport%"},
    )
    assert update_resp.status_code == 200
    updated_rule = update_resp.json()
    assert updated_rule["priority"] == 12
    assert updated_rule["description_pattern"] == "%airport%"

    delete_resp = client.delete(f"/categories/rules/{rule_id}")
    assert delete_resp.status_code == 200
    deleted_rule = delete_resp.json()
    assert deleted_rule["active"] is False


def test_backfill_unmapped_and_manual_override_precedence(client: TestClient, db_engine):
    category_ids = _seed_category_reference_data(db_engine)

    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO accounts (id, name, platform, account_type, currency, country) VALUES
                  (1, 'DBS Savings', 'DBS', 'BANK', 'SGD', 'SG')
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO transactions (
                  id, ts, account_id, amount, type, currency, category, merchant_counterparty, notes
                ) VALUES
                  (1, '2026-02-04 12:00:00+00:00', 1, -20, 'EXPENSE', 'SGD', NULL, 'Coffee Shop', 'latte'),
                  (2, '2026-02-08 12:00:00+00:00', 1, -10, 'EXPENSE', 'SGD', 'Uncategorized', 'Unknown', 'mystery'),
                  (3, '2026-02-10 12:00:00+00:00', 1, 120, 'INCOME', 'SGD', 'Brokerage::Dividend', 'Broker', NULL),
                  (4, '2026-02-12 12:00:00+00:00', 1, -500, 'TRANSFER', 'SGD', 'Bank::Transfer', 'Own Account', NULL)
                """
            )
        )

    unmapped_resp = client.get("/categories/unmapped?month=2026-02")
    assert unmapped_resp.status_code == 200
    unmapped = unmapped_resp.json()
    assert [row["transaction_id"] for row in unmapped] == [2, 1]

    backfill_resp = client.post("/categories/backfill")
    assert backfill_resp.status_code == 200
    assert backfill_resp.json() == {"created": 2, "updated": 0}

    resolution_resp = client.get("/categories/resolve/3")
    assert resolution_resp.status_code == 200
    resolution = resolution_resp.json()
    assert resolution["raw_category"] == "Brokerage::Dividend"
    assert resolution["override_category"] == "Dividends"
    assert resolution["resolved_category"] == "Dividends"
    assert resolution["source"] == "rule"
    assert resolution["rule_name"] == "Bridge Brokerage Dividends"

    override_resp = client.post(
        "/categories/override",
        json={"transaction_id": 3, "category_id": category_ids["salary"]},
    )
    assert override_resp.status_code == 200
    override_resolution = override_resp.json()
    assert override_resolution["override_category"] == "Salary"
    assert override_resolution["resolved_category"] == "Salary"
    assert override_resolution["source"] == "manual"
    assert override_resolution["rule_id"] is None

    second_backfill_resp = client.post("/categories/backfill")
    assert second_backfill_resp.status_code == 200
    assert second_backfill_resp.json() == {"created": 0, "updated": 0}

    persisted_resp = client.get("/categories/resolve/3")
    assert persisted_resp.status_code == 200
    assert persisted_resp.json()["resolved_category"] == "Salary"
    assert persisted_resp.json()["source"] == "manual"


def test_spending_endpoints_use_resolved_categories(client: TestClient, db_engine, seed_spending_data):
    category_ids = _seed_category_reference_data(db_engine)

    override_resp = client.post(
        "/categories/override",
        json={"transaction_id": 7, "category_id": category_ids["rideshare"]},
    )
    assert override_resp.status_code == 200

    summary_resp = client.get("/spending/summary?month=2026-02&base_currency=SGD")
    assert summary_resp.status_code == 200
    expense_categories = {
        item["category"]: item["amount"] for item in summary_resp.json()["expense_categories"]
    }
    assert expense_categories["Rideshare"] == 1780.0

    detail_resp = client.get("/spending/credit-card-transactions?month=2026-02&base_currency=SGD")
    assert detail_resp.status_code == 200
    transactions = {item["description"]: item for item in detail_resp.json()["transactions"]}
    hawker_tx = transactions["Hawker Center"]
    assert hawker_tx["category"] == "Dining"
    assert hawker_tx["resolved_category"] == "Rideshare"
    assert hawker_tx["category_source"] == "manual"

    cash_flow_resp = client.get("/spending/cash-flow-detail?month=2026-02&base_currency=SGD")
    assert cash_flow_resp.status_code == 200
    expense_transactions = {
        item["merchant_counterparty"]: item
        for item in cash_flow_resp.json()["expenses"]["transactions"]
    }
    cash_flow_hawker_tx = expense_transactions["Hawker Center"]
    assert cash_flow_hawker_tx["raw_category"] == "Dining"
    assert cash_flow_hawker_tx["resolved_category"] == "Rideshare"
    assert cash_flow_hawker_tx["resolved_category_id"] == category_ids["rideshare"]
    assert cash_flow_hawker_tx["category_source"] == "manual"


def test_transfer_override_excludes_row_from_cash_flow_totals(
    client: TestClient, db_engine, seed_spending_data
):
    category_ids = _seed_category_reference_data(db_engine)

    override_resp = client.post(
        "/categories/override",
        json={"transaction_id": 1, "category_id": category_ids["internal_transfer"]},
    )
    assert override_resp.status_code == 200
    assert override_resp.json()["resolved_category"] == "Internal Transfer"

    summary_resp = client.get("/spending/summary?month=2026-02&base_currency=SGD")
    assert summary_resp.status_code == 200
    summary = summary_resp.json()
    assert summary["income_total"] == 480.0
    assert summary["expense_total"] == 8710.0
    assert summary["net"] == -8230.0
    income_categories = {item["category"]: item["amount"] for item in summary["income_categories"]}
    assert income_categories == {"Dividends": 480.0}

    cash_flow_resp = client.get("/spending/cash-flow-detail?month=2026-02&base_currency=SGD")
    assert cash_flow_resp.status_code == 200
    cash_flow = cash_flow_resp.json()
    assert cash_flow["income_total"] == 480.0
    assert cash_flow["net"] == -8230.0
    assert cash_flow["income"]["transaction_count"] == 1
    assert [item["merchant_counterparty"] for item in cash_flow["income"]["transactions"]] == ["Broker"]
    assert all(
        item["merchant_counterparty"] != "Employer"
        for item in cash_flow["income"]["transactions"]
    )
