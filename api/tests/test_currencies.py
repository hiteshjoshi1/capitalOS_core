from fastapi.testclient import TestClient


def test_currencies_create_and_list(client: TestClient):
    resp = client.post("/currencies", json={"code": "USD", "name": "US Dollar", "country": "United States"})
    assert resp.status_code == 200
    created = resp.json()
    assert created["code"] == "USD"
    assert created["country"] == "United States"

    resp = client.get("/currencies")
    assert resp.status_code == 200
    data = resp.json()
    assert any(c["code"] == "USD" for c in data)
