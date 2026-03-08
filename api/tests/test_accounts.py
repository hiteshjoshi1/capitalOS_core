from fastapi.testclient import TestClient
from sqlalchemy import text

def test_accounts_list_empty(client: TestClient):
    resp = client.get("/accounts")
    assert resp.status_code == 200
    assert resp.json() == []


def test_accounts_create_validation(client: TestClient):
    resp = client.post(
        "/accounts",
        json={
            "name": " ",
            "platform": "DBS",
            "platform_id": None,
            "account_type": "BANK",
            "currency": "SGD",
            "country": "SG",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "name is required"

def test_accounts_options(client: TestClient, db_engine):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platforms (id, code, name, platform_type, country, website) VALUES "
                "(1, 'DBS', 'DBS Bank', 'BANK', 'SG', NULL)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO currencies (id, code, name, country) VALUES "
                "(1, 'SGD', 'Singapore Dollar', 'Singapore')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, platform_id) VALUES "
                "(1, 'DBS Savings', 'DBS', 'BANK', 'SGD', 'SG', 1)"
            )
        )

    resp = client.get("/accounts/options")
    assert resp.status_code == 200
    data = resp.json()
    assert "BANK" in data["account_types"]
    assert "SGD" in data["currencies"]
    assert "SG" in data["countries"]
    assert data["currency_pattern"] == "^[A-Z]{3}$"


def test_accounts_create_and_list(client: TestClient, db_engine):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platforms (id, code, name, platform_type, country, website) VALUES "
                "(1, 'CITI', 'Citibank', 'BANK', 'US', NULL)"
            )
        )

    payload = {
        "name": "DBS Savings",
        "platform": "SHOULD_BE_OVERRIDDEN",
        "platform_id": 1,
        "account_type": "BANK",
        "currency": "SGD",
        "country": "SG",
    }
    create = client.post("/accounts", json=payload)
    assert create.status_code == 200
    created = create.json()
    assert created["name"] == "DBS Savings"
    assert created["platform_id"] == 1
    assert created["platform"] == "CITI"
    assert created["country"] == "SG"

    with db_engine.begin() as conn:
        cur = conn.execute(text("SELECT code FROM currencies WHERE code='SGD'")).fetchone()
        assert cur is not None

    resp = client.get("/accounts")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "DBS Savings"
