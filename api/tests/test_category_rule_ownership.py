from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.auth_context import CurrentUser, require_current_user
from app.category_engine import apply_rules
from app.main import app

SYSTEM_RULE_ID = 1000
RIDESHARE = 121


@contextmanager
def act_as(user_id: int, *, admin: bool = False):
    app.dependency_overrides[require_current_user] = lambda: CurrentUser(
        id=user_id, username=f"user{user_id}", is_admin=admin
    )
    try:
        yield
    finally:
        app.dependency_overrides.pop(require_current_user, None)


@pytest.fixture()
def seeded(db_engine):
    now = datetime.now(tz=timezone.utc)
    with db_engine.begin() as conn:
        for user_id in (2, 3):
            conn.execute(
                text(
                    """
                    INSERT INTO users (id, username, display_name, is_active, is_admin, created_at, updated_at)
                    VALUES (:id, :username, :username, 1, 0, :now, :now)
                    """
                ),
                {"id": user_id, "username": f"user{user_id}", "now": now},
            )
        conn.execute(
            text(
                """
                INSERT INTO category_taxonomy (id, code, name, parent_id, display_order) VALUES
                  (120, 'transportation', 'Transportation', NULL, 40),
                  (121, 'transportation_rideshare', 'Rideshare', 120, 41),
                  (160, 'uncategorized', 'Uncategorized', NULL, 110)
                """
            )
        )
        # A shared system rule (user_id NULL), like the migration-seeded defaults.
        conn.execute(
            text(
                """
                INSERT INTO category_rules (id, name, priority, merchant_pattern, target_category_id, active)
                VALUES (1000, 'System default', 50, '%SYSTEMSHOP%', 160, 1)
                """
            )
        )


def _create_rule(client: TestClient, name: str, pattern: str = "%GRAB%") -> dict:
    response = client.post(
        "/categories/rules",
        json={"name": name, "priority": 10, "merchant_pattern": pattern, "target_category_id": RIDESHARE},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _names(client: TestClient) -> set[str]:
    response = client.get("/categories/rules")
    assert response.status_code == 200
    return {rule["name"] for rule in response.json()}


def test_users_only_see_shared_and_their_own_rules(client, seeded):
    with act_as(2):
        _create_rule(client, "user2 rule")
    with act_as(3):
        _create_rule(client, "user3 rule")

    with act_as(2):
        assert _names(client) == {"System default", "user2 rule"}
    with act_as(3):
        assert _names(client) == {"System default", "user3 rule"}


def test_a_user_cannot_change_or_delete_another_users_rule(client, seeded):
    with act_as(2):
        rule_id = _create_rule(client, "user2 rule")["id"]

    with act_as(3):
        # Indistinguishable from a rule that does not exist.
        assert client.put(f"/categories/rules/{rule_id}", json={"priority": 1}).status_code == 404
        assert client.delete(f"/categories/rules/{rule_id}").status_code == 404

    with act_as(2):
        updated = client.put(f"/categories/rules/{rule_id}", json={"priority": 7})
        assert updated.status_code == 200
        assert updated.json()["priority"] == 7
        assert client.delete(f"/categories/rules/{rule_id}").json()["active"] is False


def test_rule_owner_cannot_be_reassigned_through_the_api(client, db_engine, seeded):
    with act_as(2):
        rule_id = _create_rule(client, "user2 rule")["id"]
        client.put(f"/categories/rules/{rule_id}", json={"user_id": 3, "priority": 9})

    with db_engine.connect() as conn:
        owner = conn.execute(text("SELECT user_id FROM category_rules WHERE id = :id"), {"id": rule_id}).scalar()
    assert owner == 2


def test_system_rules_are_read_only_for_non_admins(client, seeded):
    with act_as(2):
        assert client.put(f"/categories/rules/{SYSTEM_RULE_ID}", json={"priority": 1}).status_code == 403
        assert client.delete(f"/categories/rules/{SYSTEM_RULE_ID}").status_code == 403

    with act_as(2, admin=True):
        assert client.put(f"/categories/rules/{SYSTEM_RULE_ID}", json={"priority": 5}).status_code == 200
        assert client.delete(f"/categories/rules/{SYSTEM_RULE_ID}").status_code == 200


def test_admin_cannot_touch_another_users_rule(client, seeded):
    with act_as(2):
        rule_id = _create_rule(client, "user2 rule")["id"]
    with act_as(3, admin=True):
        assert client.put(f"/categories/rules/{rule_id}", json={"priority": 1}).status_code == 404


def test_a_users_rule_only_categorizes_that_users_transactions(db_engine, seeded):
    now = datetime.now(tz=timezone.utc).isoformat()
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO accounts (id, name, platform, account_type, currency, country, user_id) VALUES
                  (21, 'u2 bank', 'DBS', 'BANK', 'SGD', 'SG', 2),
                  (31, 'u3 bank', 'DBS', 'BANK', 'SGD', 'SG', 3)
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO transactions (id, ts, account_id, amount, type, currency, category, merchant_counterparty)
                VALUES
                  (201, :ts, 21, -10, 'EXPENSE', 'SGD', NULL, 'GRAB RIDE'),
                  (301, :ts, 31, -10, 'EXPENSE', 'SGD', NULL, 'GRAB RIDE'),
                  (202, :ts, 21, -5, 'EXPENSE', 'SGD', NULL, 'SYSTEMSHOP'),
                  (302, :ts, 31, -5, 'EXPENSE', 'SGD', NULL, 'SYSTEMSHOP')
                """
            ),
            {"ts": now},
        )
        conn.execute(
            text(
                """
                INSERT INTO category_rules (id, name, priority, merchant_pattern, target_category_id, active, user_id)
                VALUES (2000, 'user2 grab', 10, '%GRAB%', 121, 1, 2)
                """
            )
        )

    session = sessionmaker(bind=db_engine)()
    try:
        apply_rules(session, [201, 301, 202, 302])
        session.commit()
    finally:
        session.close()

    with db_engine.connect() as conn:
        applied = {
            int(row[0]): int(row[1])
            for row in conn.execute(text("SELECT transaction_id, rule_id FROM category_overrides"))
        }
    # user2's private rule reaches user2's transaction only; the system rule reaches both users.
    assert applied.get(201) == 2000
    assert 301 not in applied
    assert applied.get(202) == SYSTEM_RULE_ID
    assert applied.get(302) == SYSTEM_RULE_ID
