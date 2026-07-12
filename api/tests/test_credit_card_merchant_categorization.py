"""
Tests for credit card merchant categorization (Issue 195).

Covers:
1. The merchant_categorizer module (parser-level classification)
2. The broadened /categories/unmapped filter (CreditCard::Purchase is now surfaced)
3. Backfill with seed rules resolves common merchant categories
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ingestion.parsers.merchant_categorizer import classify_merchant


# ──────────────────────────────────────────────────────────────────────────────
# 1.  Merchant categorizer unit tests (no DB required)
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "description,merchant,expected",
    [
        # Groceries
        ("SHENG SIONG - SS - A3 SINGAPORE SGP", None, "Groceries"),
        ("NTUC FAIRPRICE CO-OP LTD SG", None, "Groceries"),
        ("COLD STORAGE (MARINA SQ) SG", None, "Groceries"),
        ("GIANT HYPERMARKET TAMPINES", None, "Groceries"),
        ("REDMART LIMITED SINGAPORE", None, "Groceries"),
        ("DON DON DONKI DOWNTOWN LINE", None, "Groceries"),
        # Dining
        ("KOPITIAM FP APP PAYMENTS SINGAPORE SG", None, "Dining"),
        ("MCDONALD'S OUTLETS SINGAPORE", None, "Dining"),
        ("STARBUCKS COFFEE MARINA BAY", None, "Dining"),
        ("SUBWAY RESTAURANTS SG", None, "Dining"),
        ("KFC BUGIS JUNCTION", None, "Dining"),
        ("PIZZA HUT DELIVERY", None, "Dining"),
        # Food delivery (also maps to Dining)
        ("GRAB FOOD ORDER SG", None, "Dining"),
        ("FOODPANDA SG DELIVERY", None, "Dining"),
        ("DELIVEROO SINGAPORE", None, "Dining"),
        # Subscriptions
        ("NETFLIX.COM", None, "Subscriptions"),
        ("SPOTIFY AB SWEDEN", None, "Subscriptions"),
        ("ADOBE SYSTEMS INC", None, "Subscriptions"),
        ("OPENAI * CHATGPT", None, "Subscriptions"),
        ("GITHUB INC", None, "Subscriptions"),
        ("AMAZON PRIME MEMBERSHIP", None, "Subscriptions"),
        # Transport
        ("GRAB*TAXI", None, "Transport"),
        ("GOJEK SINGAPORE", None, "Transport"),
        ("EZ LINK PTE LTD", None, "Transport"),
        # Travel
        ("SINGAPORE AIRLINES LTD", None, "Travel"),
        ("SCOOT TIGERAIR", None, "Travel"),
        ("BOOKING.COM B.V.", None, "Travel"),
        ("AIRBNB INC", None, "Travel"),
        ("AGODA COMPANY PTE LTD", None, "Travel"),
        # Shopping
        ("LAZADA SINGAPORE", None, "Shopping"),
        ("SHOPEE SG MARKETPLACE", None, "Shopping"),
        ("AMAZON.COM PURCHASE", None, "Shopping"),
        ("UNIQLO SINGAPORE", None, "Shopping"),
        # Utilities
        ("SINGTEL PTE LTD SG", None, "Utilities"),
        ("STARHUB LTD SINGAPORE", None, "Utilities"),
        ("SP SERVICES LTD SG", None, "Utilities"),
        # Medical
        ("GUARDIAN PHARMACY CAUSEWAY PT", None, "Medical"),
        ("WATSONS PERSONAL CARE STORES", None, "Medical"),
        # Grab Food must beat generic Grab rule
        ("GRAB FOOD DELIVERY SG", None, "Dining"),
        ("GRABFOOD.COM", None, "Dining"),
        # Unknown → fallback
        ("SOME RANDOM MERCHANT XYZ", None, "CreditCard::Purchase"),
        ("", None, "CreditCard::Purchase"),
    ],
)
def test_classify_merchant(description: str, merchant, expected: str):
    result = classify_merchant(description, merchant)
    assert result == expected, f"classify_merchant({description!r}) → {result!r}, want {expected!r}"


def test_classify_merchant_uses_merchant_counterparty_when_provided():
    # merchant_counterparty takes priority over description
    result = classify_merchant("SOME GENERIC DESCRIPTION", "KOPITIAM BUGIS")
    assert result == "Dining"


def test_classify_merchant_grabs_food_delivery_before_grab_transport():
    """GRAB FOOD should resolve to Dining, not Transport."""
    assert classify_merchant("GRAB FOOD SG", None) == "Dining"
    assert classify_merchant("GRAB*RIDE SG", None) == "Transport"


# ──────────────────────────────────────────────────────────────────────────────
# 2.  Broadened /categories/unmapped filter
# ──────────────────────────────────────────────────────────────────────────────


def _seed_cc_account_and_transactions(db_engine, transactions: list[dict]) -> int:
    """Insert a credit card account and the given transaction rows; return account_id."""
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country) VALUES "
                "(900, 'Test CC', 'CITI', 'CREDIT_CARD', 'SGD', 'SG')"
            )
        )
        for tx in transactions:
            conn.execute(
                text(
                    "INSERT INTO transactions "
                    "(id, ts, account_id, amount, type, currency, category, merchant_counterparty, notes) "
                    "VALUES (:id, :ts, 900, :amount, :type, 'SGD', :category, :merchant, NULL)"
                ),
                tx,
            )
    return 900


def test_unmapped_filter_surfaces_creditcard_purchase_placeholder(
    client: TestClient, db_engine
):
    """Transactions with CreditCard::Purchase must appear in /categories/unmapped."""
    _seed_cc_account_and_transactions(
        db_engine,
        [
            {
                "id": 901,
                "ts": "2026-02-10 12:00:00+00:00",
                "amount": -50,
                "type": "EXPENSE",
                "category": "CreditCard::Purchase",
                "merchant": "UNKNOWN MERCHANT SG",
            },
            {
                "id": 902,
                "ts": "2026-02-11 12:00:00+00:00",
                "amount": -30,
                "type": "EXPENSE",
                "category": "Dining",        # already classified; should NOT appear
                "merchant": "KOPITIAM BUGIS",
            },
            {
                "id": 903,
                "ts": "2026-02-12 12:00:00+00:00",
                "amount": -20,
                "type": "EXPENSE",
                "category": None,             # NULL → classic unmapped; should appear
                "merchant": "NO CATEGORY",
            },
        ],
    )

    resp = client.get("/categories/unmapped?month=2026-02")
    assert resp.status_code == 200
    unmapped_ids = {row["transaction_id"] for row in resp.json()}

    # CreditCard::Purchase placeholder → surfaced
    assert 901 in unmapped_ids
    # Already classified with a real category → NOT surfaced
    assert 902 not in unmapped_ids
    # NULL category → surfaced (existing behaviour)
    assert 903 in unmapped_ids


def test_unmapped_filter_excludes_already_overridden_transactions(
    client: TestClient, db_engine
):
    """Transactions that already have a category_override must not appear in unmapped."""
    _seed_category_reference_data_minimal(db_engine)
    _seed_cc_account_and_transactions(
        db_engine,
        [
            {
                "id": 910,
                "ts": "2026-02-10 12:00:00+00:00",
                "amount": -50,
                "type": "EXPENSE",
                "category": "CreditCard::Purchase",
                "merchant": "SOME MERCHANT",
            },
        ],
    )
    # Add a manual override for tx 910
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO category_overrides (transaction_id, category_id, source) "
                "VALUES (910, :cat_id, 'manual')"
            ),
            {"cat_id": _get_dining_category_id(db_engine)},
        )

    resp = client.get("/categories/unmapped?month=2026-02")
    assert resp.status_code == 200
    unmapped_ids = {row["transaction_id"] for row in resp.json()}
    assert 910 not in unmapped_ids


# ──────────────────────────────────────────────────────────────────────────────
# 3.  Backfill with seed rules resolves common merchants
# ──────────────────────────────────────────────────────────────────────────────


def _seed_full_category_reference_data(db_engine):
    """Seed taxonomy + rules mirroring migration 027 + 064 patterns for tests."""
    with db_engine.begin() as conn:
        # Taxonomy
        conn.execute(
            text(
                """
                INSERT INTO category_taxonomy (id, code, name, parent_id, display_order) VALUES
                  (1, 'income', 'Income', NULL, 10),
                  (30, 'food_dining', 'Food & Dining', NULL, 30),
                  (31, 'food_dining_groceries', 'Groceries', 30, 31),
                  (32, 'food_dining_restaurants', 'Dining Out', 30, 32),
                  (40, 'transportation', 'Transportation', NULL, 40),
                  (41, 'transportation_public', 'Public Transit', 40, 41),
                  (42, 'transportation_rideshare', 'Rideshare', 40, 42),
                  (50, 'shopping', 'Shopping', NULL, 50),
                  (51, 'shopping_general', 'General Shopping', 50, 51),
                  (70, 'entertainment', 'Entertainment', NULL, 70),
                  (71, 'entertainment_subscriptions', 'Subscriptions', 70, 71),
                  (80, 'financial', 'Financial', NULL, 80),
                  (100, 'transfer', 'Transfer', NULL, 100),
                  (152, 'transfer_credit_card_payment', 'Credit Card Payment', 100, 102),
                  (110, 'uncategorized', 'Uncategorized', NULL, 110),
                  (45, 'travel', 'Travel', NULL, 45),
                  (46, 'travel_flights', 'Flights', 45, 46),
                  (47, 'travel_hotel', 'Hotels', 45, 47),
                  (48, 'travel_booking', 'Travel Bookings', 45, 48),
                  (55, 'utilities', 'Utilities', NULL, 55),
                  (56, 'utilities_telecom', 'Telecom', 55, 56),
                  (60, 'health', 'Health', NULL, 60),
                  (61, 'health_medical', 'Medical', 60, 61),
                  (62, 'health_pharmacy', 'Pharmacy', 60, 62)
                """
            )
        )
        # Merchant pattern rules (subset matching the categories above)
        conn.execute(
            text(
                """
                INSERT INTO category_rules
                  (id, name, priority, merchant_pattern, source_category_pattern, target_category_id, active)
                VALUES
                  (201, 'CC Merchant: Sheng Siong Groceries',   200, '%SHENG SIONG%',   'CreditCard::Purchase', 31,  1),
                  (202, 'CC Merchant: NTUC FairPrice Groceries',201, '%FAIRPRICE%',      'CreditCard::Purchase', 31,  1),
                  (210, 'CC Merchant: Grab Food Delivery',      210, '%GRAB FOOD%',      'CreditCard::Purchase', 32,  1),
                  (211, 'CC Merchant: Foodpanda Delivery',      212, '%FOODPANDA%',      'CreditCard::Purchase', 32,  1),
                  (220, 'CC Merchant: Kopitiam Dining',         220, '%KOPITIAM%',       'CreditCard::Purchase', 32,  1),
                  (221, 'CC Merchant: Starbucks Dining',        221, '%STARBUCKS%',      'CreditCard::Purchase', 32,  1),
                  (230, 'CC Merchant: Netflix Subscription',    230, '%NETFLIX%',        'CreditCard::Purchase', 71,  1),
                  (231, 'CC Merchant: Spotify Subscription',    231, '%SPOTIFY%',        'CreditCard::Purchase', 71,  1),
                  (250, 'CC Merchant: Grab Transport',          250, '%GRAB%',           'CreditCard::Purchase', 42,  1),
                  (260, 'CC Merchant: SIA Travel',              260, '%SINGAPORE AIRLINES%','CreditCard::Purchase', 46,  1),
                  (264, 'CC Merchant: Booking.com Travel',      264, '%BOOKING.COM%',    'CreditCard::Purchase', 47,  1),
                  (270, 'CC Merchant: Lazada Shopping',         270, '%LAZADA%',         'CreditCard::Purchase', 51,  1),
                  (271, 'CC Merchant: Shopee Shopping',         271, '%SHOPEE%',         'CreditCard::Purchase', 51,  1),
                  -- Bridge rules for parser-assigned categories
                  (300, 'Bridge CC Groceries to taxonomy',      300, NULL, 'Groceries',     31,  1),
                  (301, 'Bridge CC Dining to taxonomy',         301, NULL, 'Dining',        32,  1),
                  (302, 'Bridge CC Transport to taxonomy',      302, NULL, 'Transport',     42,  1),
                  (303, 'Bridge CC Subscriptions to taxonomy',  303, NULL, 'Subscriptions', 71,  1),
                  (304, 'Bridge CC Shopping to taxonomy',       304, NULL, 'Shopping',      51,  1),
                  (305, 'Bridge CC Travel to taxonomy',         305, NULL, 'Travel',        45,  1),
                  (306, 'Bridge CC Utilities to taxonomy',      306, NULL, 'Utilities',     55,  1),
                  (307, 'Bridge CC Medical to taxonomy',        307, NULL, 'Medical',       61,  1)
                """
            )
        )


def _seed_category_reference_data_minimal(db_engine):
    """Minimal taxonomy without rules (for unmapped filter tests)."""
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO category_taxonomy (id, code, name, parent_id, display_order) VALUES
                  (30, 'food_dining', 'Food & Dining', NULL, 30),
                  (32, 'food_dining_restaurants', 'Dining Out', 30, 32),
                  (110, 'uncategorized', 'Uncategorized', NULL, 110)
                """
            )
        )


def _get_dining_category_id(db_engine) -> int:
    with db_engine.connect() as conn:
        row = conn.execute(
            text("SELECT id FROM category_taxonomy WHERE code = 'food_dining_restaurants' LIMIT 1")
        ).fetchone()
        return int(row[0]) if row else 32


def test_backfill_resolves_creditcard_purchase_by_merchant_pattern(
    client: TestClient, db_engine
):
    """After backfill, known merchants with CreditCard::Purchase get resolved_category."""
    _seed_full_category_reference_data(db_engine)

    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country) VALUES "
                "(920, 'DBS CC', 'DBS', 'CREDIT_CARD', 'SGD', 'SG')"
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO transactions
                  (id, ts, account_id, amount, type, currency, category, merchant_counterparty, notes)
                VALUES
                  (921, '2026-02-10 12:00:00+00:00', 920, -50, 'EXPENSE', 'SGD',
                   'CreditCard::Purchase', 'SHENG SIONG - A1 SINGAPORE', NULL),
                  (922, '2026-02-11 12:00:00+00:00', 920, -15, 'EXPENSE', 'SGD',
                   'CreditCard::Purchase', 'NETFLIX.COM', NULL),
                  (923, '2026-02-12 12:00:00+00:00', 920, -8, 'EXPENSE', 'SGD',
                   'CreditCard::Purchase', 'GRAB*RIDES SG', NULL),
                  -- Unknown merchant stays as CreditCard::Purchase
                  (924, '2026-02-13 12:00:00+00:00', 920, -99, 'EXPENSE', 'SGD',
                   'CreditCard::Purchase', 'SOME MYSTERY SHOP', NULL)
                """
            )
        )

    # Before backfill: all four should appear in unmapped (all have CreditCard::Purchase)
    unmapped_resp = client.get("/categories/unmapped?month=2026-02")
    assert unmapped_resp.status_code == 200
    unmapped_ids_before = {row["transaction_id"] for row in unmapped_resp.json()}
    assert {921, 922, 923, 924}.issubset(unmapped_ids_before)

    # Run backfill
    backfill_resp = client.post("/categories/backfill")
    assert backfill_resp.status_code == 200
    result = backfill_resp.json()
    # SHENG SIONG → Groceries, NETFLIX → Subscriptions, GRAB → Transport = 3 resolved
    assert result["created"] == 3
    assert result["updated"] == 0

    # After backfill: classified transactions no longer appear in unmapped
    unmapped_resp2 = client.get("/categories/unmapped?month=2026-02")
    assert unmapped_resp2.status_code == 200
    unmapped_ids_after = {row["transaction_id"] for row in unmapped_resp2.json()}
    assert 921 not in unmapped_ids_after   # SHENG SIONG → resolved
    assert 922 not in unmapped_ids_after   # NETFLIX → resolved
    assert 923 not in unmapped_ids_after   # GRAB → resolved
    assert 924 in unmapped_ids_after       # unknown → still unmapped

    # Verify resolved categories via the category resolution endpoint
    for tx_id, expected_name in [(921, "Groceries"), (922, "Subscriptions"), (923, "Rideshare")]:
        res_resp = client.get(f"/categories/resolve/{tx_id}")
        assert res_resp.status_code == 200
        assert res_resp.json()["resolved_category"] == expected_name, \
            f"tx {tx_id}: {res_resp.json()}"


def test_backfill_bridges_parser_assigned_friendly_categories_to_taxonomy(
    client: TestClient, db_engine
):
    """Transactions with parser-emitted friendly categories (Dining, Groceries, …)
    are resolved to the taxonomy name by the bridge rules after backfill."""
    _seed_full_category_reference_data(db_engine)

    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country) VALUES "
                "(930, 'UOB CC', 'UOB', 'CREDIT_CARD', 'SGD', 'SG')"
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO transactions
                  (id, ts, account_id, amount, type, currency, category, merchant_counterparty, notes)
                VALUES
                  (931, '2026-02-10 12:00:00+00:00', 930, -50, 'EXPENSE', 'SGD',
                   'Groceries', 'SHENG SIONG - A1', NULL),
                  (932, '2026-02-11 12:00:00+00:00', 930, -20, 'EXPENSE', 'SGD',
                   'Dining', 'KOPITIAM BUGIS', NULL),
                  (933, '2026-02-12 12:00:00+00:00', 930, -15, 'EXPENSE', 'SGD',
                   'Subscriptions', 'NETFLIX.COM', NULL),
                  (934, '2026-02-13 12:00:00+00:00', 930, -30, 'EXPENSE', 'SGD',
                   'Transport', 'GRAB*RIDES SG', NULL)
                """
            )
        )

    # These transactions do NOT appear in unmapped (they have real friendly names,
    # not CreditCard::Purchase)
    unmapped_resp = client.get("/categories/unmapped?month=2026-02")
    assert unmapped_resp.status_code == 200
    unmapped_ids = {row["transaction_id"] for row in unmapped_resp.json()}
    for tx_id in (931, 932, 933, 934):
        assert tx_id not in unmapped_ids

    # After backfill, bridge rules map them to taxonomy names
    backfill_resp = client.post("/categories/backfill")
    assert backfill_resp.status_code == 200
    assert backfill_resp.json()["created"] == 4

    expected = {
        931: "Groceries",      # food_dining_groceries
        932: "Dining Out",     # food_dining_restaurants
        933: "Subscriptions",  # entertainment_subscriptions
        934: "Rideshare",      # transportation_rideshare
    }
    for tx_id, expected_name in expected.items():
        res_resp = client.get(f"/categories/resolve/{tx_id}")
        assert res_resp.status_code == 200
        assert res_resp.json()["resolved_category"] == expected_name, \
            f"tx {tx_id}: {res_resp.json()}"


def test_credit_card_transactions_endpoint_returns_multiple_categories(
    client: TestClient, db_engine
):
    """GET /spending/credit-card-transactions must show multiple resolved_category
    values when the account has mixed merchant types."""
    _seed_full_category_reference_data(db_engine)

    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country) VALUES "
                "(940, 'DBS Platinum', 'DBS', 'CREDIT_CARD', 'SGD', 'SG')"
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO transactions
                  (id, ts, account_id, amount, type, currency, category, merchant_counterparty, notes)
                VALUES
                  (941, '2026-05-10 12:00:00+00:00', 940, -50, 'EXPENSE', 'SGD',
                   'Groceries', 'SHENG SIONG BUGIS', NULL),
                  (942, '2026-05-11 12:00:00+00:00', 940, -20, 'EXPENSE', 'SGD',
                   'Dining', 'KOPITIAM MARINA', NULL),
                  (943, '2026-05-12 12:00:00+00:00', 940, -15, 'EXPENSE', 'SGD',
                   'Subscriptions', 'NETFLIX.COM', NULL)
                """
            )
        )

    resp = client.get("/spending/credit-card-transactions?month=2026-05&base_currency=SGD")
    assert resp.status_code == 200
    transactions = resp.json()["transactions"]
    resolved_categories = {tx["resolved_category"] for tx in transactions if tx["type"] == "EXPENSE"}
    # Without backfill, resolved_category comes from raw category (parser-emitted friendly names)
    assert len(resolved_categories) > 1, \
        f"Expected multiple categories, got: {resolved_categories}"
    assert "Groceries" in resolved_categories
    assert "Dining" in resolved_categories
    assert "Subscriptions" in resolved_categories
