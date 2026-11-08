"""#332: every part of Catch-up, Newly tracked and Unexplained names its items (which
holding, account, card, token), largest first; a part's items add up to it.
Synthetic numbers only."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.valuation import bridge as b
from tests.valuation_household import SCENARIOS, build_scenario, household_env


def test_items_are_largest_first_capped_with_a_rest_that_adds_up():
    rows = [b._item(f"H{i}", float(i)) for i in range(1, 12)] + [b._item("tiny", 0.2)]
    items = b._items(rows, total=sum(range(1, 12)) + 0.2)
    assert [i["label"] for i in items[:3]] == ["H11", "H10", "H9"]
    assert len(items) == b.ITEMS_MAX + 1 and items[-1]["label"] == "Rest"
    assert sum(i["amount"] for i in items) == pytest.approx(sum(range(1, 12)) + 0.2)


def test_no_rest_item_when_the_list_covers_the_part():
    items = b._items([b._item("A", 10.0), b._item("B", -4.0)], total=6.0)
    assert [i["label"] for i in items] == ["A", "B"]


@pytest.fixture
def mid(client: TestClient, db_engine, monkeypatch):
    household_env(monkeypatch, SCENARIOS["mid"])
    build_scenario(db_engine, "mid")
    return client


def test_household_parts_name_their_items_and_add_up(mid: TestClient):
    resp = mid.get("/dashboard/month-bridge?month=2026-03&base_currency=SGD")
    assert resp.status_code == 200, resp.text
    bridge = resp.json()
    named = [line for line in bridge["lines"] if line["key"] in {"catch_up", "newly_tracked"}] + [bridge["unexplained"]]
    for line in named:
        for part in line["parts"]:
            if not part["items"]:
                continue
            assert sum(i["amount"] or 0.0 for i in part["items"]) == pytest.approx(part["amount"], abs=0.01), part["key"]
    parts = {p["key"]: p for p in bridge["unexplained"]["parts"]}
    # RELIANCE bought at Sharekhan (no cash record) is named, with the reason.
    untracked = parts["untracked_trades"]["items"]
    assert untracked[0]["label"].startswith("RELIANCE") and "no cash record at Sharekhan" in untracked[0]["reason"]
    # The card part names the household's card, with a link to fix it.
    cards = parts["card_balances"]["items"]
    assert cards and all(item["link"] == "/liabilities" for item in cards)
    assert all(item["label"] and item["reason"] for item in cards)
    # Other always ends with what it can't name, so it still adds up.
    other = parts["other"]
    assert sum(i["amount"] or 0.0 for i in other["items"]) == pytest.approx(other["amount"], abs=0.01)
