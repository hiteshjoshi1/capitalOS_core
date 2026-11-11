"""History → Compare (#398, D-110): the bridge from month A's close to month B's,
the sum of the month bridges A+1 … B, on the synthetic household.

- It adds up exactly (Decimal, before the float edge), each line's parts add up to it.
- A→C equals A→B + B→C line by line, and its ends are the month bridges' ends.
- A = B is no change; A after B, a future month and too long a span are refused.
- Months with no data at the start still add up.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.valuation import span_bridge
from app.valuation.money import D, dsum
from tests.valuation_household import SCENARIOS, USER_A, build_scenario, household_env


@pytest.fixture
def mid(client: TestClient, db_engine, monkeypatch):
    """The household on 18 March 2026 (data from late 2025; March is the open month)."""
    household_env(monkeypatch, SCENARIOS["mid"])
    build_scenario(db_engine, "mid")
    return client


def _get(client: TestClient, path: str) -> dict[str, Any]:
    resp = client.get(path)
    assert resp.status_code == 200, (path, resp.text)
    return resp.json()


def _span(client: TestClient, a: str, b: str, base: str = "SGD") -> dict[str, Any]:
    return _get(client, f"/dashboard/bridge?from={a}&to={b}&base_currency={base}&limit=20")


def _amounts(bridge: dict[str, Any]) -> dict[str, float]:
    return {line["key"]: line["amount"] for line in bridge["lines"]}


def _adds_up(bridge: dict[str, Any]) -> None:
    total = bridge["start"]["value"] + sum(line["amount"] for line in bridge["lines"]) + bridge["unexplained"]["amount"]
    assert total == pytest.approx(bridge["end"]["value"], abs=1e-6)
    for line in [*bridge["lines"], bridge["unexplained"]]:
        if line["parts"]:
            assert sum(p["amount"] for p in line["parts"]) == pytest.approx(line["amount"], abs=1e-6), line["key"]
        for part in line["parts"]:
            if part["items"] and all(i["amount"] is not None for i in part["items"]):
                assert sum(i["amount"] for i in part["items"]) == pytest.approx(part["amount"], abs=1e-6), part["key"]


@pytest.mark.parametrize("base", ("SGD", "USD"))
def test_span_adds_up_exactly_before_the_float_edge(mid: TestClient, db_engine, base: str):
    db = Session(bind=db_engine)
    try:
        exact = span_bridge.span_bridge.__wrapped__(db, USER_A, "2025-12", "2026-03", base, movers_limit=20)
        rows = [*exact["lines"], exact["unexplained"]]
        assert all(isinstance(line["amount"], Decimal) for line in rows)
        assert D(exact["start"]["value"]) + dsum(line["amount"] for line in rows) == D(exact["end"]["value"])
        assert D(exact["change"]) == D(exact["end"]["value"]) - D(exact["start"]["value"])
        for line in rows:
            if line["parts"]:
                assert dsum(p["amount"] for p in line["parts"]) == D(line["amount"]), line["key"]
    finally:
        db.close()


def test_span_is_the_sum_of_its_months(mid: TestClient):
    """Jan→Mar = Jan→Feb + Feb→Mar, line by line, and its ends are the month bridges' ends."""
    feb = _get(mid, "/dashboard/month-bridge?month=2026-02&base_currency=SGD&limit=20")
    mar = _get(mid, "/dashboard/month-bridge?month=2026-03&base_currency=SGD&limit=20")
    span = _span(mid, "2026-01", "2026-03")
    _adds_up(span)
    assert span["is_live"] is True
    assert [m["month"] for m in span["months"]] == ["2026-02", "2026-03"]
    assert span["start"]["value"] == pytest.approx(feb["start"]["value"], abs=1e-6)
    assert span["end"]["value"] == pytest.approx(mar["end"]["value"], abs=1e-6)
    assert span["start"]["month"] == "2026-01"
    keys = set(_amounts(feb)) | set(_amounts(mar))
    assert set(_amounts(span)) == keys
    for key in keys:
        expected = _amounts(feb).get(key, 0.0) + _amounts(mar).get(key, 0.0)
        assert _amounts(span)[key] == pytest.approx(expected, abs=1e-6), key
    assert span["unexplained"]["amount"] == pytest.approx(feb["unexplained"]["amount"] + mar["unexplained"]["amount"], abs=1e-6)
    # Two spans that meet add up to the longer one.
    jan_feb, feb_mar = _span(mid, "2026-01", "2026-02"), _span(mid, "2026-02", "2026-03")
    for key in keys:
        assert _amounts(span)[key] == pytest.approx(
            _amounts(jan_feb).get(key, 0.0) + _amounts(feb_mar).get(key, 0.0), abs=1e-6
        ), key
    for mover in span["movers"]:
        assert mover["change"] == pytest.approx(mover["end_value"] - mover["start_value"], abs=1e-6)


def test_same_month_is_no_change(mid: TestClient):
    span = _span(mid, "2026-02", "2026-02")
    assert span["change"] == 0
    assert span["lines"] == [] and span["unexplained"]["amount"] == 0
    assert span["start"] == span["end"]
    assert span["months"] == []


@pytest.mark.parametrize(
    "a,b",
    (("2026-03", "2026-02"), ("2026-02", "2026-05"), ("2020-01", "2026-03"), ("2026-13", "2026-03")),
    ids=("from_after_to", "future", "too_long", "bad_month"),
)
def test_refused_spans(mid: TestClient, a: str, b: str):
    resp = mid.get(f"/dashboard/bridge?from={a}&to={b}")
    assert resp.status_code == 422, resp.text


def test_months_without_data_still_add_up(mid: TestClient):
    """Starting long before the first statement: the start is empty, the lines and
    Unexplained still reach the end."""
    span = _span(mid, "2024-01", "2026-02")
    _adds_up(span)
    assert span["start"]["value"] == 0
    assert span["start"]["baseline_missing"] is True
    assert len(span["months"]) == 25
