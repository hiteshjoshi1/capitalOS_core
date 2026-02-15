from fastapi.testclient import TestClient
from sqlalchemy import text

def test_platforms_list_order(client: TestClient, db_engine):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platforms (id, code, name, platform_type, country, website) VALUES "
                "(1, 'IBKR', 'Interactive Brokers', 'BROKER', 'US', NULL), "
                "(2, 'DBS', 'DBS Bank', 'BANK', 'SG', NULL), "
                "(3, 'UOB', 'UOB', 'BANK', 'SG', NULL)"
            )
        )

    resp = client.get("/platforms")
    assert resp.status_code == 200
    data = resp.json()
    assert [p["code"] for p in data] == ["DBS", "UOB", "IBKR"]
