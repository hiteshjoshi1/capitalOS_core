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


def test_accounts_create_and_list(client: TestClient, db_engine):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platforms (id, code, name, platform_type, country, website) VALUES "
                "(1, 'DBS', 'DBS Bank', 'BANK', 'SG', NULL)"
            )
        )

    payload = {
        "name": "DBS Multiplier",
        "platform": "DBS",
        "platform_id": 1,
        "account_type": "BANK",
        "currency": "SGD",
        "country": "SG",
    }
    create = client.post("/accounts", json=payload)
    assert create.status_code == 200
    created = create.json()
    assert created["name"] == "DBS Multiplier"
    assert created["platform_id"] == 1

    resp = client.get("/accounts")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "DBS Multiplier"
