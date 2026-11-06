"""Risk concentration (#253, D-68): the thresholds a user sets in Settings, and the
currency exposure and platform concentration /dashboard/risk-summary adds.

How these figures agree with the other pages (Overview's largest positions and
platform split, the headline) is in test_one_number_contract.py."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.valuation_cache import clear_shared_cache
from tests.auth_helpers import signed_in_client
from tests.valuation_household import SCENARIOS, build_scenario, household_env

NONE = {"largest_position_warn_pct": None, "top_n_warn_pct": None, "platform_warn_pct": None}
CLIENT_USER = 1  # conftest.TEST_USER_ID, the `client` fixture's user
OTHER_USER = 25301


def test_thresholds_default_to_null_until_set(client: TestClient):
    resp = client.get("/dashboard/risk-thresholds")
    assert resp.status_code == 200, resp.text
    assert resp.json() == NONE


def test_thresholds_are_saved_per_user_and_reset_with_null(client: TestClient, db_engine):
    saved = {"largest_position_warn_pct": 20, "top_n_warn_pct": 42.5, "platform_warn_pct": None}
    resp = client.put("/dashboard/risk-thresholds", json=saved)
    assert resp.status_code == 200, resp.text
    assert resp.json() == saved
    assert client.get("/dashboard/risk-thresholds").json() == saved

    # Another user keeps the defaults.
    other = signed_in_client(db_engine, OTHER_USER)
    assert other.get("/dashboard/risk-thresholds").json() == NONE

    # Saving thresholds keeps the rest of the preferences row, and the reverse.
    client.patch("/auth/preferences", json={"theme": "light"})
    assert client.get("/auth/preferences").json()["theme"] == "light"
    assert client.get("/dashboard/risk-thresholds").json() == saved

    # PUT replaces: null puts a threshold back to the default.
    resp = client.put("/dashboard/risk-thresholds", json={**saved, "largest_position_warn_pct": None})
    assert resp.json() == {**saved, "largest_position_warn_pct": None}
    assert client.get("/auth/preferences").json()["theme"] == "light"


def test_saving_thresholds_creates_the_preferences_row_with_its_defaults(client: TestClient, db_engine):
    with db_engine.begin() as conn:
        conn.execute(text("DELETE FROM user_preferences WHERE user_id = :u"), {"u": CLIENT_USER})
    resp = client.put("/dashboard/risk-thresholds", json={**NONE, "platform_warn_pct": 60})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {**NONE, "platform_warn_pct": 60}
    prefs = client.get("/auth/preferences").json()
    assert (prefs["theme"], prefs["accent_color"]) == ("dark", "#0f7a5c")


@pytest.mark.parametrize("value", [0, -5, 100.01, 250])
def test_thresholds_outside_0_100_are_refused(client: TestClient, value):
    resp = client.put("/dashboard/risk-thresholds", json={**NONE, "top_n_warn_pct": value})
    assert resp.status_code == 422, resp.text
    assert client.get("/dashboard/risk-thresholds").json() == NONE


def test_thresholds_need_a_signed_in_user(anon_client: TestClient):
    assert anon_client.get("/dashboard/risk-thresholds").status_code == 401
    assert anon_client.put("/dashboard/risk-thresholds", json=NONE).status_code == 401


@pytest.fixture()
def mid_household(client: TestClient, db_engine, monkeypatch):
    household_env(monkeypatch, SCENARIOS["mid"])
    build_scenario(db_engine, "mid")
    return client


def _get(client: TestClient, path: str) -> dict:
    clear_shared_cache()
    resp = client.get(path)
    assert resp.status_code == 200, (path, resp.text)
    return resp.json()


@pytest.mark.parametrize("month", ["2026-03", "2026-02"])
def test_currency_exposure_places_every_part_of_net_worth(mid_household: TestClient, month):
    risk = _get(mid_household, f"/dashboard/risk-summary?month={month}&base_currency=SGD")
    view = risk["view_net_worth"]
    items = {item["currency"]: item for item in risk["currency_exposure"]["items"]}

    # Stablecoins are US dollars; other crypto is its own bucket, not a currency.
    stable = _get(mid_household, f"/crypto/stablecoins?month={month}&base_currency=SGD")
    assert items["USD"]["stablecoins"] == pytest.approx(stable["total_base"], abs=0.01)
    assert items["CRYPTO"]["crypto"] == pytest.approx(view["crypto"] - stable["total_base"], abs=0.01)
    assert {key for key, item in items.items() if item["stablecoins"] or item["crypto"]} == {"USD", "CRYPTO"}

    # The household's card is an SGD card: what it owes comes off SGD.
    assert items["SGD"]["liabilities"] == pytest.approx(view["liabilities"], abs=0.01)

    # Stocks by the currency they trade in (the household holds US and HK stocks, among others).
    assert {key for key, item in items.items() if item["stocks_funds"] > 0} >= {"USD", "HKD"}

    for item in items.values():
        assert item["value"] == pytest.approx(
            item["cash"] + item["stocks_funds"] + item["stablecoins"] + item["crypto"] - item["liabilities"], abs=1e-6
        )
    ordered = [item["value"] for item in risk["currency_exposure"]["items"]]
    assert ordered == sorted(ordered, reverse=True)
    assert sum(item["percent"] for item in items.values()) == pytest.approx(100, abs=0.05)


def test_currency_exposure_in_another_base_currency_is_the_same_split(mid_household: TestClient):
    """The split is by the currency money is held in, not the one it is shown in."""
    sgd = _get(mid_household, "/dashboard/risk-summary?month=2026-02&base_currency=SGD")["currency_exposure"]
    usd = _get(mid_household, "/dashboard/risk-summary?month=2026-02&base_currency=USD")["currency_exposure"]
    assert [item["currency"] for item in sgd["items"]] == [item["currency"] for item in usd["items"]]
    for a, b in zip(sgd["items"], usd["items"]):
        assert a["percent"] == pytest.approx(b["percent"], abs=0.02), (a, b)
