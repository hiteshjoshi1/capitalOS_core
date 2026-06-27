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

    def fake_get(url, params=None, timeout=10, **_kwargs):
        calls["count"] += 1
        if "frankfurter.app" in url:
            base = params.get("from")
            if base == "SGD":
                # Missing INR to trigger fallback, but include USD so raw_rates isn't empty.
                return FakeResponse({"rates": {"USD": 0.75}})
            if base == "EUR":
                return FakeResponse({"rates": {"SGD": 1.5, "INR": 80}})
            return FakeResponse({"rates": {}})
        if "open.er-api.com" in url:
            return FakeResponse({"rates": {}})
        return FakeResponse({"rates": {}})

    monkeypatch.setattr(fx.httpx, "get", fake_get)
    fx._CACHE.clear()
    rates = fx.get_rates(datetime(2026, 2, 6, tzinfo=timezone.utc), "SGD", ["INR"])
    assert calls["count"] == 2
    # base_rate / sym_rate = 1.5 / 80
    assert rates["INR"] == pytest.approx(1.5 / 80, rel=1e-6)


def test_get_rates_static_sgd_inr(monkeypatch):
    monkeypatch.setenv("FX_DISABLE_REMOTE", "0")
    monkeypatch.setenv("FX_FALLBACK_RATES", '{"SGD":{"INR":70}}')

    def fake_get(url, params=None, timeout=10, **_kwargs):
        raise Exception("network down")

    monkeypatch.setattr(fx.httpx, "get", fake_get)
    fx._CACHE.clear()
    rates = fx.get_rates(datetime(2026, 2, 6, tzinfo=timezone.utc), "SGD", ["INR"])
    assert rates["INR"] == pytest.approx(1.0 / 70.0, rel=1e-6)
