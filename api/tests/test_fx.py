from datetime import datetime, timezone
import pytest

from app import fx


class FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def test_get_rates_fallback_cross(monkeypatch):
    monkeypatch.setenv("FX_DISABLE_REMOTE", "0")
    calls = {"count": 0}

    def fake_get(url, params=None, timeout=10):
        calls["count"] += 1
        base = params.get("from")
        if base == "SGD":
            # Missing INR to trigger fallback
            return FakeResponse({"rates": {}})
        if base == "EUR":
            return FakeResponse({"rates": {"SGD": 1.5, "INR": 80}})
        return FakeResponse({"rates": {}})

    monkeypatch.setattr(fx.httpx, "get", fake_get)
    fx._CACHE.clear()
    rates = fx.get_rates(datetime(2026, 2, 6, tzinfo=timezone.utc), "SGD", ["INR"])
    assert calls["count"] == 2
    # base_rate / sym_rate = 1.5 / 80
    assert rates["INR"] == pytest.approx(1.5 / 80, rel=1e-6)
