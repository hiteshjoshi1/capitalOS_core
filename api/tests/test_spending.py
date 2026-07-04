from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text

from tests.canonical_test_helpers import seed_canonical_account_balance_for_test


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


def test_cash_flow_detail(client: TestClient, seed_spending_data):
    resp = client.get("/spending/cash-flow-detail?month=2026-02&base_currency=SGD")
    assert resp.status_code == 200
    data = resp.json()

    assert data["month"] == "2026-02"
    assert data["base_currency"] == "SGD"
    assert data["income_total"] == 12480.0
    assert data["expense_total"] == 8710.0
    assert data["net"] == 3770.0
    assert data["savings_rate"] == 3770.0 / 12480.0
    assert data["income"]["transaction_count"] == 2
    assert data["income"]["included_types"] == ["INCOME"]
    assert data["expenses"]["transaction_count"] == 6
    assert data["expenses"]["included_types"] == ["EXPENSE", "FEE", "TAX", "INTEREST"]

    employer_tx = data["income"]["transactions"][1]
    assert employer_tx["merchant_counterparty"] == "Employer"
    assert employer_tx["resolved_category"] == "Salary"
    assert employer_tx["resolved_category_id"] is None
    assert employer_tx["category_source"] == "parser"
    assert employer_tx["base_amount"] == 12000.0

    rent_tx = next(
        item for item in data["expenses"]["transactions"] if item["merchant_counterparty"] == "Landlord"
    )
    assert rent_tx["account_name"] == "DBS Savings"
    assert rent_tx["account_type"] == "BANK"
    assert rent_tx["raw_category"] == "Rent"
    assert rent_tx["resolved_category"] == "Rent"
    assert rent_tx["resolved_category_id"] is None
    assert rent_tx["base_amount"] == -3200.0


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
    assert first_tx["resolved_category"] == "Groceries"
    assert first_tx["category_source"] == "parser"

    assert [abs(item["amount"]) for item in data["top_purchases"]] == [1780.0, 1210.0]
    assert data["recurring_payments"] == []


def test_credit_card_recurring_payments_require_stable_monthly_amounts(client: TestClient, db_engine):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country) VALUES "
                "(510, 'UOB One Card', 'UOB', 'CREDIT_CARD', 'SGD', 'SG')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO transactions (id, ts, account_id, amount, type, currency, category, merchant_counterparty, notes) VALUES "
                "(51001, '2025-12-08 00:00:00+00:00', 510, -18, 'EXPENSE', 'SGD', 'Subscription', 'Netflix', NULL), "
                "(51002, '2026-01-08 00:00:00+00:00', 510, -18, 'EXPENSE', 'SGD', 'Subscription', 'Netflix', NULL), "
                "(51003, '2026-02-08 00:00:00+00:00', 510, -18, 'EXPENSE', 'SGD', 'Subscription', 'Netflix', NULL), "
                "(51004, '2025-12-10 00:00:00+00:00', 510, -90, 'EXPENSE', 'SGD', 'Groceries', 'NTUC FairPrice Online SINGAPORE SG', NULL), "
                "(51005, '2026-01-10 00:00:00+00:00', 510, -130, 'EXPENSE', 'SGD', 'Groceries', 'NTUC FairPrice Online SINGAPORE SG', NULL), "
                "(51006, '2026-02-10 00:00:00+00:00', 510, -65, 'EXPENSE', 'SGD', 'Groceries', 'NTUC FairPrice Online SINGAPORE SG', NULL)"
            )
        )

    resp = client.get("/spending/credit-card-transactions?month=2026-02&base_currency=SGD")
    assert resp.status_code == 200
    recurring = resp.json()["recurring_payments"]

    assert [item["merchant_counterparty"] for item in recurring] == ["Netflix"]
    assert recurring[0]["months_present"] == 3
    assert recurring[0]["current_month_amount"] == 18.0


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


def test_dbs_credit_card_pages_and_cash_flow_match_database_totals(client: TestClient, db_engine):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country) VALUES "
                "(810, 'DBS Multiplier', 'DBS', 'BANK', 'SGD', 'SG'), "
                "(811, 'DBS Credit Card', 'DBS', 'CREDIT_CARD', 'SGD', 'SG'), "
                "(812, 'DBS Vickers Cash Upfront', 'DBS_VICKERS', 'BROKER', 'SGD', 'SG')"
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO credit_card_accounts
                  (account_id, card_name, issuer, credit_limit, available_limit, available_limit_as_of, statement_day, due_day)
                VALUES
                  (811, 'DBS/POSB MasterCard Platinum (2403)', 'DBS', 60000, 59739.44,
                   '2026-07-04 00:00:00+00:00', 14, 25)
                """
            )
        )
        conn.execute(
            text(
                "INSERT INTO transactions (id, ts, account_id, amount, type, currency, category, merchant_counterparty, notes) VALUES "
                "(81101, '2026-07-02 00:00:00+00:00', 811, -100, 'EXPENSE', 'SGD', 'CreditCard::Purchase', 'SHENG SIONG', NULL), "
                "(81102, '2026-07-03 00:00:00+00:00', 811, -10, 'FEE', 'SGD', 'CreditCard::Fee', 'ANNUAL FEE', NULL), "
                "(81103, '2026-07-03 00:00:00+00:00', 811, -0.9, 'TAX', 'SGD', 'CreditCard::Tax', 'GST @ 9%', NULL), "
                "(81104, '2026-07-04 00:00:00+00:00', 811, -5, 'INTEREST', 'SGD', 'CreditCard::Interest', 'FINANCE CHARGES', NULL), "
                "(81105, '2026-07-05 00:00:00+00:00', 811, 50, 'TRANSFER', 'SGD', 'CreditCard::Payment', 'GIRO PAYMENT', NULL), "
                "(81001, '2026-07-05 00:00:00+00:00', 810, -50, 'TRANSFER', 'SGD', 'Bank::Transfer', 'GIRO PAYMENT DBS CREDIT CARD', NULL), "
                "(81201, '2026-07-08 00:00:00+00:00', 812, -999, 'TRANSFER', 'SGD', 'Brokerage::Transfer', 'DBS VICKERS FUNDING', NULL)"
            )
        )

    with db_engine.connect() as conn:
        expected_expenses = float(
            conn.execute(
                text(
                    """
                    SELECT SUM(-amount)
                    FROM transactions
                    WHERE account_id = 811
                      AND type IN ('EXPENSE','FEE','TAX','INTEREST')
                    """
                )
            ).scalar()
        )
        expected_outstanding = float(
            conn.execute(
                text(
                    """
                    SELECT credit_limit - available_limit
                    FROM credit_card_accounts
                    WHERE account_id = 811
                    """
                )
            ).scalar()
        )

    summary_resp = client.get("/spending/credit-cards?month=2026-07&base_currency=SGD")
    assert summary_resp.status_code == 200
    summary = summary_resp.json()
    assert summary["total_spend"] == pytest.approx(expected_outstanding)
    assert [card["account_name"] for card in summary["cards"]] == ["DBS Credit Card"]
    card = summary["cards"][0]
    assert card["card_name"] == "DBS/POSB MasterCard Platinum (2403)"
    assert card["issuer"] == "DBS"
    assert card["credit_limit"] == 60000.0
    assert card["available_limit"] == 59739.44
    assert card["available_limit_as_of"] == "2026-07-04T00:00:00+00:00"
    assert card["current_due"] == pytest.approx(expected_outstanding)
    assert card["current_due_source"] == "available_limit"

    detail_resp = client.get("/spending/credit-card-transactions?month=2026-07&base_currency=SGD")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert len(detail["transactions"]) == 5
    assert {tx["account_name"] for tx in detail["transactions"]} == {"DBS Credit Card"}
    assert {tx["type"] for tx in detail["transactions"]} == {"EXPENSE", "FEE", "TAX", "INTEREST", "TRANSFER"}
    payment = next(tx for tx in detail["transactions"] if tx["type"] == "TRANSFER")
    assert payment["amount"] == 50.0
    assert [tx["description"] for tx in detail["top_purchases"]] == ["SHENG SIONG"]
    assert detail["recurring_payments"] == []

    cash_flow_resp = client.get("/spending/cash-flow-detail?month=2026-07&base_currency=SGD")
    assert cash_flow_resp.status_code == 200
    cash_flow = cash_flow_resp.json()
    assert cash_flow["expense_total"] == pytest.approx(expected_expenses)
    assert cash_flow["expenses"]["transaction_count"] == 4
    assert all(tx["type"] != "TRANSFER" for tx in cash_flow["expenses"]["transactions"])


def test_cash_flow_infers_signed_non_internal_transfer_rows(client: TestClient, db_engine):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country) VALUES "
                "(700, 'DBS Multiplier', 'DBS', 'BANK', 'SGD', 'SG')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO transactions (id, ts, account_id, amount, type, currency, category, merchant_counterparty, notes) VALUES "
                "(7001, '2026-03-05 00:00:00+00:00', 700, 5000, 'INCOME', 'SGD', 'Salary', 'Employer', NULL), "
                "(7002, '2026-03-06 00:00:00+00:00', 700, -12, 'TRANSFER', 'SGD', 'Bank::ADV', 'WEI DAO PTE. LTD.', NULL), "
                "(7003, '2026-03-07 00:00:00+00:00', 700, -2000, 'TRANSFER', 'SGD', 'Bank::Transfer', 'OWN ACCOUNT TRANSFER', NULL), "
                "(7004, '2026-03-08 00:00:00+00:00', 700, -1500, 'TRANSFER', 'SGD', 'Bank::ADV', 'Transfer to IBKR', NULL)"
            )
        )

    resp = client.get("/spending/summary?month=2026-03&base_currency=SGD")
    assert resp.status_code == 200
    data = resp.json()

    assert data["income_total"] == 5000.0
    assert data["expense_total"] == 0.0
    assert data["net"] == 5000.0


def test_cash_flow_counts_rent_standing_instruction_as_expense(client: TestClient, db_engine):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country) VALUES "
                "(701, 'DBS Multiplier', 'DBS', 'BANK', 'SGD', 'SG')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO transactions (id, ts, account_id, amount, type, currency, category, merchant_counterparty, notes) VALUES "
                "(7011, '2026-07-01 00:00:00+00:00', 701, 5000, 'INCOME', 'SGD', 'Salary', 'Employer', NULL), "
                "(7012, '2026-07-04 00:00:00+00:00', 701, -3450, 'TRANSFER', 'SGD', 'Bank::GR', "
                "'SI TO : YOAGARANI D REF:Rent 260704073204SI00274165', 'Payments or Collections via GIRO')"
            )
        )

    summary_resp = client.get("/spending/summary?month=2026-07&base_currency=SGD")
    assert summary_resp.status_code == 200
    summary = summary_resp.json()
    assert summary["income_total"] == 5000.0
    assert summary["expense_total"] == 3450.0
    assert summary["net"] == 1550.0
    assert summary["savings_rate"] == 1550.0 / 5000.0

    detail_resp = client.get("/spending/cash-flow-detail?month=2026-07&base_currency=SGD")
    assert detail_resp.status_code == 200
    expenses = detail_resp.json()["expenses"]["transactions"]
    rent_tx = next(
        item for item in expenses if item["merchant_counterparty"].startswith("SI TO : YOAGARANI D")
    )
    assert rent_tx["type"] == "TRANSFER"
    assert rent_tx["base_amount"] == -3450.0


def test_cash_flow_detail_includes_deterministic_analytics(client: TestClient, db_engine, seed_spending_data):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(900, 'SGD-CASH', 'Singapore Dollar Cash', 'CASH', 'SGD', 'SG')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO transactions (id, ts, account_id, amount, type, currency, category, merchant_counterparty, notes) VALUES "
                "(11, '2026-01-05 12:00:00+00:00', 10, 10000, 'INCOME', 'SGD', 'Salary', 'Employer', NULL), "
                "(12, '2026-01-08 09:00:00+00:00', 10, 300, 'INCOME', 'SGD', 'Dividends', 'Broker', NULL), "
                "(13, '2026-01-10 12:00:00+00:00', 10, -2800, 'EXPENSE', 'SGD', 'Rent', 'Landlord', NULL), "
                "(14, '2026-01-15 12:00:00+00:00', 10, -400, 'EXPENSE', 'SGD', 'Transport', 'Transit', NULL), "
                "(15, '2026-01-18 12:00:00+00:00', 11, -900, 'EXPENSE', 'SGD', 'Groceries', 'Supermarket', NULL)"
            )
        )
    seed_canonical_account_balance_for_test(
        db_engine,
        account_id=10,
        as_of="2026-01-31",
        currency="SGD",
        balance_base=11000,
        balance_type="bank_cash",
    )
    seed_canonical_account_balance_for_test(
        db_engine,
        account_id=10,
        as_of="2026-02-28",
        currency="SGD",
        balance_base=15000,
        balance_type="bank_cash",
    )

    resp = client.get("/spending/cash-flow-detail?month=2026-02&base_currency=SGD")
    assert resp.status_code == 200
    data = resp.json()
    analytics = data["analytics"]

    assert analytics["prior_month"] == "2026-01"
    assert analytics["prior_month_net"] == 6182.0
    assert analytics["free_cash_flow_change_vs_prior_month"] == -2412.0
    assert analytics["burn_rate"] == 8710.0 / 12480.0
    assert analytics["waterfall"] == {
        "starting_cash": 11000.0,
        "snapshot_start_as_of": "2026-01-31T00:00:00+00:00",
        "snapshot_start_boundary_at": "2026-02-01T00:00:00+00:00",
        "inflows": 12480.0,
        "outflows": 8710.0,
        "transfers_and_funding": 0.0,
        "investment_and_fx_effects": 230.0,
        "other_cash_movements": 230.0,
        "snapshot_end_as_of": "2026-02-28T00:00:00+00:00",
        "snapshot_end_boundary_at": "2026-03-01T00:00:00+00:00",
        "boundary_exact": False,
        "availability_message": "Cash reconciliation needs exact cash snapshots on 2026-02-01 and 2026-03-01. Available snapshots are 2026-01-31 and 2026-02-28.",
        "ending_cash": 15000.0,
    }

    outflow_categories = {item["label"]: item for item in analytics["outflow_categories"]}
    assert outflow_categories["Rent"]["amount"] == 3200.0
    assert outflow_categories["Rent"]["percent"] == 3200.0 / 8710.0

    inflow_mix = {item["label"]: item for item in analytics["inflow_source_mix"]}
    assert inflow_mix["Salary"]["amount"] == 12000.0
    assert inflow_mix["Dividends"]["amount"] == 480.0

    outflow_deltas = {item["label"]: item for item in analytics["outflow_category_deltas"]}
    assert outflow_deltas["Rent"]["delta_amount"] == 400.0
    assert outflow_deltas["Dining"]["delta_amount"] == 1780.0

    top_merchant = analytics["top_outflow_merchants"][0]
    assert top_merchant["merchant"] == "Landlord"
    assert top_merchant["amount"] == 3200.0

    assert [point["month"] for point in analytics["trend"]][-2:] == ["2026-01", "2026-02"]
    assert analytics["trend"][-1]["net"] == 3770.0
    assert analytics["trend"][-1]["savings_rate"] == 3770.0 / 12480.0
    assert analytics["answers"][0]["question"] == "Where did my money go this month?"
    assert analytics["answers"][2]["answer"] == "Saved 30.2% and spent 69.8% of inflows."
    assert analytics["answers"][3]["answer"] == (
        "Net cash flow was 3770 this month versus 6182 in 2026-01, "
        "a -2412 change. Inflows changed by +2180 and outflows changed by +4592. "
        "Savings rate moved from 60.0% to 30.2%."
    )


def test_cash_flow_saved_vs_spent_answer_handles_negative_net_without_absurd_percentages(client: TestClient, db_engine):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(901, 'SGD-CASH-NEG', 'Singapore Dollar Cash Negative', 'CASH', 'SGD', 'SG')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country) VALUES "
                "(910, 'UOB Spend', 'UOB', 'BANK', 'SGD', 'SG')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO transactions (id, ts, account_id, amount, type, currency, category, merchant_counterparty, notes) VALUES "
                "(91011, '2026-02-05 00:00:00+00:00', 910, 1000, 'INCOME', 'SGD', 'Salary', 'Employer', NULL), "
                "(91012, '2026-02-12 00:00:00+00:00', 910, -6500, 'EXPENSE', 'SGD', 'Travel', 'Airline', NULL)"
            )
        )
    seed_canonical_account_balance_for_test(
        db_engine,
        account_id=910,
        as_of="2026-01-31",
        currency="SGD",
        balance_base=9000,
        balance_type="bank_cash",
    )
    seed_canonical_account_balance_for_test(
        db_engine,
        account_id=910,
        as_of="2026-02-28",
        currency="SGD",
        balance_base=3500,
        balance_type="bank_cash",
    )

    resp = client.get("/spending/cash-flow-detail?month=2026-02&base_currency=SGD")
    assert resp.status_code == 200
    answer = resp.json()["analytics"]["answers"][2]["answer"]
    assert answer == (
        "Saved 0.0% of inflows and spent 100.0% of them. "
        "Outflows exceeded inflows by 5500, which had to come from existing cash or other funding sources."
    )
