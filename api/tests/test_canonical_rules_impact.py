"""The #242 impact script (app.scripts.canonical_rules_impact) finds exactly the
parity test's #242 edges, agrees with the live coverage reader, and prints no
amounts or names."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.portfolio.canonical_reads import canonical_snapshot_coverage_as_of
from app.scripts.canonical_rules_impact import coverage_as_of, measure, report
from tests.test_canonical_read_parity import (
    FLEX_OWNED_UPLOAD_DATE,
    SECOND_BROKER_DATE,
    add_242_edges,
    add_edges,
)
from tests.valuation_household import IBKR, SCENARIOS, SHAREKHAN, USER_A, USER_B, build_scenario, household_env

START, END = date(2026, 1, 1), date(2026, 4, 15)


def _days(first: date, last: date = END) -> set[tuple[int, date]]:
    return {(USER_A, first + timedelta(days=n)) for n in range((last - first).days + 1)}


def _build(db_engine, monkeypatch, *, edges_242: bool):
    household_env(monkeypatch, SCENARIOS["first"])
    build_scenario(db_engine, "first")
    add_edges(db_engine)
    if edges_242:
        add_242_edges(db_engine)
    return Session(bind=db_engine)


def test_impact_is_nothing_on_the_household(db_engine, monkeypatch):
    db = _build(db_engine, monkeypatch, edges_242=False)
    try:
        impact = measure(db, start=START, end=END)
    finally:
        db.close()
    assert impact.users == [USER_A, USER_B]
    # IBKR has a Flex and an uploaded broker account (the #231 edge), but Flex routing separates them.
    assert set(impact.multi_broker_legacy_accounts) == {IBKR}
    assert impact.position_pairs == {False: set(), True: set()}
    assert impact.coverage_pairs == set()


def test_impact_finds_the_242_edges(db_engine, monkeypatch):
    db = _build(db_engine, monkeypatch, edges_242=True)
    try:
        impact = measure(db, start=START, end=END)
        for user in (USER_A, USER_B):
            for n in range((END - START).days + 1):
                day = START + timedelta(days=n)
                assert coverage_as_of(db, user, day, routed=True) == canonical_snapshot_coverage_as_of(
                    db, current_user_id=user, anchor_date=day
                )
    finally:
        db.close()
    assert set(impact.multi_broker_legacy_accounts) == {IBKR, SHAREKHAN}
    assert impact.position_pairs[False] == _days(SECOND_BROKER_DATE)
    assert impact.position_pairs[True] == _days(SECOND_BROKER_DATE)
    assert impact.position_legacy_accounts == {SHAREKHAN}
    assert impact.rows_now_shown and not impact.rows_no_longer_shown  # the new rule only adds rows
    assert impact.coverage_pairs == _days(FLEX_OWNED_UPLOAD_DATE)
    assert impact.coverage_flex_owned_accounts == {IBKR}
    text = "\n".join(report(impact))
    for secret in ("777", "55.0", "RELIANCE", "Sharekhan", "IBKR Main", "2830"):
        assert secret not in text
