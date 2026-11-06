"""Parity of the canonical read layer (#231, #130 10.2).

The canonical readers are built from one definition (``app/portfolio/effective_facts.py``).
This test pins that the rewrite changed nothing: on the valuation household of the
golden scenarios (tests/valuation_household.py), plus a few edge cases the goldens
don't reach (closed accounts, card statements older than 45 days and in two
currencies, reference rows, an uploaded IBKR broker account that Flex takes over,
incomplete scopes), every reader returns exactly what its frozen pre-#231 copy
(tests/canonical_reads_reference.py) returns, for both users, at every day from
December 2025 to mid-April 2026.

It runs on SQLite (the default suite) and on Postgres 16 (``-m postgres``, via
``make db-schema-check``), where DATE columns are real dates.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Callable, Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.market_data.service import held_position_rows
from app.portfolio.canonical_reads import (
    canonical_account_balance_rows,
    canonical_card_statement_rows,
    canonical_position_rows_by_legacy_account,
    canonical_snapshot_coverage_as_of,
    get_data_completeness_status,
    latest_authoritative_nav_by_legacy_account,
)
from app.portfolio.ibkr_flex import latest_authoritative_nav_by_legacy_account as nav_reexport
from app.valuation.account_status import _card_statement_dates
from app.valuation.facts import _card_statements_by_account
from tests import canonical_reads_reference as ref
from tests.canonical_test_helpers import seed_canonical_position_snapshot_for_test
from tests.postgres_support import migrated_database_copy
from tests.valuation_household import (
    AAPL,
    B_CARD,
    DBS_CARD,
    HSBC_USD,
    IBKR,
    MISFILED_CARD,
    RELIANCE,
    SCENARIOS,
    SHAREKHAN,
    USER_A,
    USER_B,
    build_scenario,
    household_env,
)

FIRST_ANCHOR = date(2025, 12, 1)
LAST_ANCHOR = date(2026, 4, 15)


def _anchors(step: int = 1) -> list[date]:
    """Every ``step``-th day from FIRST_ANCHOR to LAST_ANCHOR, plus every 1st of a month."""
    out, day, n = [], FIRST_ANCHOR, 0
    while day <= LAST_ANCHOR:
        if n % step == 0 or day.day == 1:
            out.append(day)
        day += timedelta(days=1)
        n += 1
    return out


def _card_statement(conn, account_id: int, as_of: str, currency: str, balance: float, status: str = "authoritative") -> None:
    conn.execute(
        text(
            "INSERT INTO account_balance_snapshots (account_id, as_of_date, currency, balance_type, "
            "balance_local, balance_base, fx_rate_to_base, authority_status, source_kind, metadata_json) "
            "VALUES (:a, :d, :c, 'credit_balance', :b, :b, 1, :s, 'backfill', '{}')"
        ),
        {"a": account_id, "d": as_of, "c": currency, "b": balance, "s": status},
    )


def add_edges(engine: Engine) -> None:
    """Edge cases on top of the household (none of them in the goldens)."""
    with engine.begin() as conn:
        # Closed accounts (D-52): a bank account mid-February, a card on 1 March.
        conn.execute(text("UPDATE accounts SET closed_on = '2026-02-25' WHERE id = :a"), {"a": HSBC_USD})
        conn.execute(text("UPDATE accounts SET closed_on = '2026-03-01' WHERE id = :a"), {"a": MISFILED_CARD})
        # Card statements: one that ages past 45 days, a two-currency one, a reference row.
        _card_statement(conn, DBS_CARD, "2025-12-05", "SGD", -500.0)
        _card_statement(conn, DBS_CARD, "2026-01-20", "SGD", -900.0)
        _card_statement(conn, DBS_CARD, "2026-01-20", "USD", -50.0)
        _card_statement(conn, DBS_CARD, "2026-03-05", "SGD", -1234.0, status="reference")
        _card_statement(conn, B_CARD, "2026-03-25", "SGD", -300.0)
        # An incomplete scope on the Flex account, a day without a Flex report.
        run = conn.execute(
            text(
                "SELECT r.id, r.broker_account_id FROM broker_import_runs r "
                "JOIN broker_accounts ba ON ba.id = r.broker_account_id "
                "WHERE ba.legacy_account_id = :a ORDER BY r.id LIMIT 1"
            ),
            {"a": IBKR},
        ).first()
        if run is not None:
            conn.execute(
                text(
                    "INSERT INTO portfolio_data_completeness (broker_account_id, import_run_id, report_date, "
                    "fact_scope, completeness_status, missing_reason, metadata_json) "
                    "VALUES (:b, :r, '2026-02-15', 'trades', 'incomplete', 'synthetic gap', '{}')"
                ),
                {"b": run[1], "r": run[0]},
            )
    # IBKR holdings uploaded into a second (non-Flex) broker account of the IBKR
    # account, before and after the Flex window starts: Flex routing decides.
    for as_of, quantity in (("2026-01-15", 18), ("2026-02-10", 21)):
        seed_canonical_position_snapshot_for_test(
            engine,
            account_id=IBKR,
            asset_id=AAPL,
            as_of=as_of,
            quantity=quantity,
            market_value_base=quantity * 250.0,
            market_price=185.0,
            currency="USD",
            platform_code="IBKR",
        )
    # A reference Sharekhan snapshot: never read, and doesn't move the latest date.
    seed_canonical_position_snapshot_for_test(
        engine,
        account_id=SHAREKHAN,
        asset_id=RELIANCE,
        as_of="2026-03-20",
        quantity=99,
        market_value_base=99 * 2900.0,
        market_price=2900.0,
        currency="INR",
        platform_code="SHAREKHAN",
        authority_status="reference",
    )


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _as_bag(rows: list[dict[str, Any]]) -> list[str]:
    return sorted(_canonical(row) for row in rows)


Check = tuple[str, Callable[[Session, int, date], Any], Callable[[Session, int, date], Any], bool]

# (name, reference, live, ordered): ordered readers must also return rows in the same order.
CHECKS: list[Check] = [
    (
        "positions",
        lambda db, u, d: ref.ref_positions(db, current_user_id=u, anchor_date=d),
        lambda db, u, d: canonical_position_rows_by_legacy_account(db, current_user_id=u, anchor_date=d),
        False,
    ),
    (
        "positions_with_nav_accounts",
        lambda db, u, d: ref.ref_positions(db, current_user_id=u, anchor_date=d, include_nav_accounts=True),
        lambda db, u, d: canonical_position_rows_by_legacy_account(
            db, current_user_id=u, anchor_date=d, include_nav_accounts=True
        ),
        False,
    ),
    (
        "balances",
        lambda db, u, d: ref.ref_balances(db, current_user_id=u, anchor_date=d),
        lambda db, u, d: canonical_account_balance_rows(db, current_user_id=u, anchor_date=d),
        True,
    ),
    (
        "coverage",
        lambda db, u, d: ref.ref_coverage(db, current_user_id=u, anchor_date=d),
        lambda db, u, d: canonical_snapshot_coverage_as_of(db, current_user_id=u, anchor_date=d),
        True,
    ),
    (
        "coverage_without_cash",
        lambda db, u, d: ref.ref_coverage(db, current_user_id=u, anchor_date=d, include_cash=False),
        lambda db, u, d: canonical_snapshot_coverage_as_of(db, current_user_id=u, anchor_date=d, include_cash=False),
        True,
    ),
    (
        "coverage_nav_only",
        lambda db, u, d: ref.ref_coverage(db, current_user_id=u, anchor_date=d, include_positions=False, include_cash=False),
        lambda db, u, d: canonical_snapshot_coverage_as_of(
            db, current_user_id=u, anchor_date=d, include_positions=False, include_cash=False
        ),
        True,
    ),
    (
        "completeness",
        lambda db, u, d: ref.ref_completeness(db, current_user_id=u, anchor_date=d),
        lambda db, u, d: get_data_completeness_status(db, current_user_id=u, anchor_date=d),
        False,
    ),
    (
        "nav",
        lambda db, u, d: ref.ref_nav(db, current_user_id=u, anchor_date=d),
        lambda db, u, d: latest_authoritative_nav_by_legacy_account(db, current_user_id=u, anchor_date=d),
        False,
    ),
    (
        "nav_via_ibkr_flex",
        lambda db, u, d: ref.ref_nav(db, current_user_id=u, anchor_date=d),
        lambda db, u, d: nav_reexport(db, current_user_id=u, anchor_date=d),
        False,
    ),
    (
        "card_statements",
        lambda db, u, d: ref.ref_card_statements(db, current_user_id=u, anchor_date=d),
        lambda db, u, d: _card_statements_by_account(
            canonical_card_statement_rows(db, current_user_id=u, anchor_date=d), "SGD"
        ),
        True,
    ),
    (
        "card_statement_dates",
        lambda db, u, d: ref.ref_card_statement_dates(db, d, u),
        lambda db, u, d: _card_statement_dates(db, d, u),
        True,
    ),
    (
        "held_positions",
        lambda db, u, d: ref.ref_held_positions(db, today=d, user_id=u),
        lambda db, u, d: held_position_rows(db, today=d, user_id=u),
        False,
    ),
    (
        "held_positions_all_users",
        lambda db, u, d: ref.ref_held_positions(db, today=d, user_id=None),
        lambda db, u, d: held_position_rows(db, today=d, user_id=None),
        False,
    ),
]


def assert_parity(engine: Engine, *, step: int = 1) -> dict[str, int]:
    """Every reader against its reference at every anchor; returns how many
    (user, anchor) pairs had a non-empty result per reader, so a check that
    never saw data can't pass silently."""
    seen: dict[str, int] = {name: 0 for name, *_ in CHECKS}
    mismatches: list[str] = []
    db = Session(bind=engine)
    try:
        for user_id in (USER_A, USER_B):
            for anchor in _anchors(step):
                for name, reference, live, ordered in CHECKS:
                    expected = reference(db, user_id, anchor)
                    actual = live(db, user_id, anchor)
                    if isinstance(expected, list):
                        same = (
                            [_canonical(r) for r in expected] == [_canonical(r) for r in actual]
                            if ordered
                            else _as_bag(expected) == _as_bag(actual)
                        )
                    else:
                        same = _canonical(expected) == _canonical(actual)
                    if not same:
                        mismatches.append(f"{name} user={user_id} anchor={anchor}: {expected!r} != {actual!r}")
                    if expected:
                        seen[name] += 1
    finally:
        db.close()
    assert not mismatches, "\n".join(mismatches[:20])
    return seen


def _assert_coverage(seen: dict[str, int]) -> None:
    empty = sorted(name for name, count in seen.items() if count == 0)
    assert not empty, f"readers that never returned anything: {empty}"


@pytest.fixture()
def sqlite_household(db_engine, monkeypatch) -> Iterator[Callable[[str], Engine]]:
    def _build(scenario: str) -> Engine:
        household_env(monkeypatch, SCENARIOS[scenario])
        build_scenario(db_engine, scenario)
        add_edges(db_engine)
        return db_engine

    yield _build


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_canonical_readers_match_the_pre_231_readers(scenario: str, sqlite_household):
    _assert_coverage(assert_parity(sqlite_household(scenario)))


@pytest.mark.postgres
@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_canonical_readers_match_the_pre_231_readers_on_postgres(scenario: str, monkeypatch):
    with migrated_database_copy() as engine:
        household_env(monkeypatch, SCENARIOS[scenario])
        build_scenario(engine, scenario)
        add_edges(engine)
        # Every other day keeps the Postgres job short; SQLite checks every day.
        _assert_coverage(assert_parity(engine, step=2))


def test_the_edge_cases_are_reached(sqlite_household):
    """The edges above really exercise each rule (else parity on them proves little)."""
    engine = sqlite_household("first")
    db = Session(bind=engine)
    try:
        def ibkr_positions(day: date) -> list[dict[str, Any]]:
            return [
                row
                for row in canonical_position_rows_by_legacy_account(db, current_user_id=USER_A, anchor_date=day)
                if int(row["account_id"]) == IBKR
            ]

        def card_dates(day: date) -> dict[int, date]:
            return _card_statement_dates(db, day, USER_A)

        def balance_accounts(day: date) -> set[int]:
            return {
                int(row["account_id"])
                for row in canonical_account_balance_rows(db, current_user_id=USER_A, anchor_date=day)
            }

        # Before the Flex window the uploaded IBKR holdings count; once Flex owns the account (and its
        # NAV values it), they don't.
        assert [row["quantity"] for row in ibkr_positions(date(2026, 1, 20))] == [18.0]
        assert ibkr_positions(date(2026, 2, 15)) == []
        # A statement counts for 45 days (D-52), in both its currencies; a reference row never.
        jan20 = _card_statements_by_account(
            canonical_card_statement_rows(db, current_user_id=USER_A, anchor_date=date(2026, 1, 25)), "SGD"
        )
        assert sorted(jan20[DBS_CARD][1]) == [("SGD", -900.0), ("USD", -50.0)]
        assert str(card_dates(date(2026, 3, 6))[DBS_CARD]) == "2026-01-20"
        assert DBS_CARD not in card_dates(date(2026, 3, 7))
        # A closed account counts up to and including its close date.
        assert HSBC_USD in balance_accounts(date(2026, 2, 25))
        assert HSBC_USD not in balance_accounts(date(2026, 2, 26))
        # The reference Sharekhan snapshot is never read.
        assert all(
            row["quantity"] != 99.0
            for row in canonical_position_rows_by_legacy_account(db, current_user_id=USER_A, anchor_date=date(2026, 3, 25))
        )
        # The incomplete scope is reported.
        assert any(
            row["fact_scope"] == "trades"
            for row in get_data_completeness_status(db, current_user_id=USER_A, anchor_date=date(2026, 2, 20))
        )
    finally:
        db.close()
