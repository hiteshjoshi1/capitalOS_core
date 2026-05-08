from fastapi.testclient import TestClient


def test_health_contract(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_dashboard_summary_contract_shape(client: TestClient, seed_dashboard_data):
    resp = client.get("/dashboard/summary?month=2026-02&compare=prev_month")
    assert resp.status_code == 200
    body = resp.json()

    assert body["as_of_month"] == "2026-02"
    assert body["base_currency"] == "SGD"
    assert "net_worth_snapshot_as_of" in body
    assert "net_worth_boundary_at" in body
    assert "net_worth_boundary_exact" in body
    assert "net_worth_freshness_status" in body
    assert set(body["net_worth"].keys()) == {
        "total",
        "cash",
        "stocks_funds",
        "crypto",
        "liabilities",
    }
    assert isinstance(body["cash_percent"], float)
    assert "cash_flow" in body
    assert "top_holdings" in body
    assert "net_worth_component_change" in body
    assert body["top_holdings"]
    assert {
        "symbol",
        "asset_class",
        "value",
        "percent_of_networth",
    }.issubset(body["top_holdings"][0].keys())


def test_ai_sage_chat_routes_are_in_openapi(client: TestClient):
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    assert "/ai-sage/chats" in paths
    assert "/ai-sage/chats/search" in paths
    assert "/ai-sage/chats/{chat_id}" in paths
    assert "/ai-sage/chats/{chat_id}/messages" in paths
    assert "/ai-sage/chats/{chat_id}/messages/{message_id}/retry" in paths
