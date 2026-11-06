"""Source freshness (#252, D-67): per-source last data date, cadence and overdue.

Synthetic data only. The cadence arithmetic is tested as pure functions (weekends
on weekday feeds, month ends, leap years, never-loaded sources); the endpoint per
source type, with overrides and owner scoping; and the per-account dates against
``account_data_status`` on the golden household (the same canonical facts)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.portfolio.canonical_reads import canonical_latest_fact_dates
from app.services import source_freshness as sf
from app.valuation.account_status import account_data_status
from app.valuation.clock import _date_only
from app.valuation_cache import clear_shared_cache
from tests.auth_helpers import auth_headers, ensure_user
from tests.canonical_test_helpers import (
    seed_canonical_account_balance_for_test,
    seed_canonical_position_snapshot_for_test,
)
from tests.valuation_household import SCENARIOS, SGT, USER_A, build_household, household_env

# Fri 6 Nov 2026; the week around it.
FRI = date(2026, 11, 6)
SAT, SUN, MON, TUE, WED, THU = (FRI + timedelta(days=n) for n in range(1, 7))


# ─── Cadence arithmetic ──────────────────────────────────────────────────────


def _status(last, cadence, grace, today):
    return sf.evaluate(last, cadence, grace, today)


def test_weekday_feed_is_on_time_over_the_weekend():
    # Quotes (grace 1): Friday's close is fine all weekend and on Monday and Tuesday.
    for today in (SAT, SUN, MON, TUE):
        assert _status(FRI, "weekdays", 1, today)["overdue"] is False, today
    assert sf.due_date(FRI, "weekdays", 1) == TUE
    late = _status(FRI, "weekdays", 1, WED)
    assert late == {"status": "overdue", "due_date": TUE, "overdue": True, "days_overdue": 1}


def test_flex_default_tolerates_its_one_day_lag_and_one_missed_run():
    # IBKR Flex reports the previous US day at 18:30 SGT: on Tuesday morning the
    # newest is Friday's. Two weekdays of grace: Friday's is fine through Wednesday.
    cadence, grace = sf.DEFAULTS[sf.KIND_IBKR_FLEX]
    assert (cadence, grace) == ("weekdays", 2)
    assert sf.due_date(FRI, cadence, grace) == WED
    assert _status(FRI, cadence, grace, THU)["days_overdue"] == 1
    # Thursday's report is due by the next Tuesday (the weekend doesn't count).
    assert sf.due_date(FRI - timedelta(days=1), cadence, grace) == TUE


def test_weekday_feed_without_grace_and_data_dated_on_a_weekend():
    assert sf.due_date(FRI, "weekdays", 0) == MON
    assert _status(FRI, "weekdays", 0, TUE)["days_overdue"] == 1
    # A Saturday-dated row counts like Friday's (no weekday passed in between).
    assert sf.due_date(SAT, "weekdays", 1) == TUE


def test_daily_and_weekly_cadences():
    assert sf.due_date(FRI, "daily", 1) == SUN
    assert _status(FRI, "daily", 1, MON) == {"status": "overdue", "due_date": SUN, "overdue": True, "days_overdue": 1}
    assert sf.due_date(FRI, "daily", 0) == SAT
    assert sf.due_date(FRI, "weekly", 3) == FRI + timedelta(days=10)


@pytest.mark.parametrize(
    ("last", "months", "expected"),
    [
        (date(2026, 1, 31), 1, date(2026, 2, 28)),  # clamped to February's end
        (date(2028, 1, 31), 1, date(2028, 2, 29)),  # leap year
        (date(2026, 10, 31), 1, date(2026, 11, 30)),
        (date(2026, 11, 30), 1, date(2026, 12, 30)),
        (date(2026, 12, 31), 1, date(2027, 1, 31)),  # year boundary
        (date(2026, 11, 30), 3, date(2027, 2, 28)),
        (date(2026, 10, 15), 1, date(2026, 11, 15)),
    ],
)
def test_add_months_clamps_to_the_month_end(last, months, expected):
    assert sf.add_months(last, months) == expected


def test_monthly_statement_is_due_a_month_and_the_grace_later():
    # A statement closing 31 Oct: November's (30 Nov) is due by 10 Dec.
    assert sf.due_date(date(2026, 10, 31), "monthly", 10) == date(2026, 12, 10)
    assert _status(date(2026, 10, 31), "monthly", 10, date(2026, 12, 10))["overdue"] is False
    assert _status(date(2026, 10, 31), "monthly", 10, date(2026, 12, 11))["days_overdue"] == 1
    # Two months old (the holdings upload case in #252): overdue by weeks.
    assert _status(date(2026, 9, 6), "monthly", 10, date(2026, 11, 6))["days_overdue"] == 21
    # Across a year end, and a quarterly source.
    assert sf.due_date(date(2026, 12, 31), "monthly", 0) == date(2027, 1, 31)
    assert sf.due_date(date(2026, 11, 30), "quarterly", 5) == date(2027, 3, 5)


def test_never_loaded_counts_as_overdue_and_off_never_does():
    assert _status(None, "monthly", 10, FRI) == {
        "status": "never_loaded",
        "due_date": None,
        "overdue": True,
        "days_overdue": None,
    }
    assert _status(None, "off", 0, FRI)["status"] == "no_schedule"
    assert _status(date(2020, 1, 1), "off", 0, FRI) == {
        "status": "no_schedule",
        "due_date": None,
        "overdue": False,
        "days_overdue": None,
    }


def test_data_dated_after_today_is_on_time():
    assert _status(MON, "monthly", 0, FRI)["status"] == "on_time"


# ─── The endpoint, per source type ───────────────────────────────────────────

TODAY = date(2026, 11, 6)
OTHER_USER = 4252


def _freeze_today(monkeypatch, today: date = TODAY) -> None:
    monkeypatch.setattr(sf, "app_today", lambda: today)


def _account(conn, account_id: int, name: str, platform: str, account_type: str, *, user_id: int = 1, closed_on=None):
    conn.execute(
        text(
            "INSERT INTO accounts (id, name, platform, user_id, account_type, currency, country, closed_on) "
            "VALUES (:id, :name, :platform, :u, :t, 'SGD', 'SG', :closed)"
        ),
        {"id": account_id, "name": name, "platform": platform, "u": user_id, "t": account_type, "closed": closed_on},
    )


def _seed_sources(db_engine) -> None:
    ensure_user(db_engine, OTHER_USER)
    with db_engine.begin() as conn:
        _account(conn, 11, "Synthetic Savings", "DBS", "BANK")
        _account(conn, 12, "Synthetic Card Statement", "DBS", "CREDIT_CARD")
        _account(conn, 13, "Synthetic Card Txns", "UOB", "CREDIT_CARD")
        _account(conn, 14, "Synthetic Holdings", "SHAREKHAN", "BROKER")
        _account(conn, 15, "Synthetic Flex", "IBKR", "BROKER")
        _account(conn, 16, "Synthetic Empty Bank", "OCBC", "BANK")
        _account(conn, 17, "Synthetic Closed Bank", "UOB", "BANK", closed_on="2026-06-30")
        _account(conn, 18, "Other User Bank", "DBS", "BANK", user_id=OTHER_USER)
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) "
                "VALUES (501, 'SYNA', 'Synthetic A', 'STOCK', 'INR', 'IN')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO market_symbol_map (asset_id, exchange_code, exchange_symbol, quote_currency, is_active) "
                "VALUES (501, 'NSE', 'SYNA', 'INR', TRUE)"
            )
        )
        # Quotes: Wednesday's close is the newest (two weekdays old on Friday).
        for day in ("2026-11-03", "2026-11-04"):
            conn.execute(
                text(
                    "INSERT INTO prices (asset_id, ts, price, currency, source, trade_date, exchange_code) "
                    "VALUES (501, :ts, 10, 'INR', 'test', :d, 'NSE')"
                ),
                {"ts": f"{day} 12:00:00", "d": day},
            )
        conn.execute(
            text(
                "INSERT INTO fx_rates (rate_date, base, quote, rate, source) "
                "VALUES ('2026-11-05', 'EUR', 'SGD', 1.5, 'frankfurter')"
            )
        )
        # Card 13: transactions only (no closing balance), newest 20 Oct.
        for day in ("2026-10-02", "2026-10-20"):
            conn.execute(
                text(
                    "INSERT INTO transactions (ts, account_id, type, amount, currency, source) "
                    "VALUES (:ts, 13, 'EXPENSE', -12.5, 'SGD', 'UOB')"
                ),
                {"ts": f"{day} 04:00:00"},
            )
        # IBKR Flex: an active flex_api connection and a NAV dated Thursday.
        conn.execute(
            text(
                "INSERT INTO broker_connections (id, user_id, platform_code, connection_type, status) "
                "VALUES (61, 1, 'IBKR', 'flex_api', 'active')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO broker_accounts (id, connection_id, legacy_account_id, broker_account_id, base_currency, status) "
                "VALUES (71, 61, 15, 'SYN-FLEX', 'USD', 'active')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO broker_import_runs (id, broker_account_id, legacy_account_id, platform_code, source_type, "
                "import_scope, status, metadata_json) VALUES (81, 71, 15, 'IBKR', 'test_fixture', 'daily', 'completed', '{}')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO portfolio_nav_snapshots (broker_account_id, import_run_id, report_date, base_currency, "
                "cash_base, stock_base, total_nav_base, authority_status) "
                "VALUES (71, 81, '2026-11-05', 'USD', 1, 2, 3, 'authoritative')"
            )
        )
        # Wallets: one refreshed yesterday, one three days ago.
        for wallet_id, label, day in (
            ("00000000-0000-4000-8000-000000000a01", "Synthetic Hot", "2026-11-05"),
            ("00000000-0000-4000-8000-000000000a02", "Synthetic Cold", "2026-11-03"),
        ):
            conn.execute(
                text(
                    "INSERT INTO crypto_wallets (id, user_id, chain_type, chain, address, label, status) "
                    "VALUES (:id, 1, 'evm', 'ethereum', :addr, :label, 'active')"
                ),
                {"id": wallet_id, "addr": f"0xsynthetic{wallet_id[-2:]}", "label": label},
            )
            conn.execute(
                text(
                    "INSERT INTO crypto_wallet_snapshots (wallet_id, as_of_date, fetched_at, total_usd) "
                    "VALUES (:id, :d, :d, 1)"
                ),
                {"id": wallet_id, "d": day},
            )
    # Bank: October's statement (31 Oct), plus a newer row that doesn't count.
    seed_canonical_account_balance_for_test(db_engine, account_id=11, as_of="2026-10-31", currency="SGD", balance_base=100)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO account_balance_snapshots (account_id, as_of_date, currency, balance_type, balance_local, "
                "balance_base, fx_rate_to_base, authority_status, source_kind, metadata_json) "
                "VALUES (11, '2026-11-05', 'SGD', 'bank_cash', 1, 1, 1, 'superseded', 'test_fixture', '{}')"
            )
        )
    # Card 12: a statement balance from August (older than valuation's 45 days).
    seed_canonical_account_balance_for_test(
        db_engine, account_id=12, as_of="2026-08-15", currency="SGD", balance_base=-50, balance_type="credit_balance"
    )
    # Holdings upload two months old: the case #252 starts from.
    seed_canonical_position_snapshot_for_test(
        db_engine, account_id=14, asset_id=501, as_of="2026-09-06", quantity=5, market_value_base=50, currency="INR"
    )
    seed_canonical_account_balance_for_test(db_engine, account_id=18, as_of="2026-11-01", currency="SGD", balance_base=9)


def _by_key(body):
    return {row["source_key"]: row for row in body["sources"]}


def test_endpoint_lists_every_source_type_with_its_cadence(client, db_engine, monkeypatch):
    monkeypatch.setenv("STOCK_EXCHANGES", "US,SGX,HKEX,NSE")
    _freeze_today(monkeypatch)
    _seed_sources(db_engine)

    resp = client.get("/dashboard/source-freshness")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    rows = _by_key(body)
    assert body["as_of"] == "2026-11-06"
    assert body["cadences"] == list(sf.CADENCES)
    # Closed accounts and other users' accounts are not sources; exchanges with
    # nothing held aren't either.
    assert set(rows) == {
        "account:11", "account:12", "account:13", "account:14", "account:15", "account:16",
        "wallet:00000000-0000-4000-8000-000000000a01", "wallet:00000000-0000-4000-8000-000000000a02",
        "exchange:NSE", "fx",
    }

    def brief(key):
        row = rows[key]
        return (row["kind"], row["last_data_date"], row["cadence"], row["grace_days"], row["status"], row["days_overdue"])

    # Bank: the superseded 5 Nov row doesn't count; 31 Oct is due by 10 Dec.
    assert brief("account:11") == ("bank_statement", "2026-10-31", "monthly", 10, "on_time", None)
    assert rows["account:11"]["due_date"] == "2026-12-10"
    # Card statement from 15 Aug: due 25 Sep, 42 days overdue.
    assert brief("account:12") == ("card_statement", "2026-08-15", "monthly", 10, "overdue", 42)
    # Card with transactions only: the newest one (20 Oct), due 30 Nov.
    assert brief("account:13") == ("card_statement", "2026-10-20", "monthly", 10, "on_time", None)
    # Holdings from 6 Sep: due 16 Oct, 21 days overdue.
    assert brief("account:14") == ("broker_statement", "2026-09-06", "monthly", 10, "overdue", 21)
    # IBKR Flex with Thursday's NAV: on time.
    assert brief("account:15") == ("ibkr_flex", "2026-11-05", "weekdays", 2, "on_time", None)
    assert brief("account:16") == ("bank_statement", None, "monthly", 10, "never_loaded", None)
    assert brief("wallet:00000000-0000-4000-8000-000000000a01") == ("crypto_wallet", "2026-11-05", "daily", 1, "on_time", None)
    # Refreshed Tuesday: due Thursday, a day overdue.
    assert brief("wallet:00000000-0000-4000-8000-000000000a02") == ("crypto_wallet", "2026-11-03", "daily", 1, "overdue", 1)
    # NSE quotes from Wednesday on a Friday: on time with one weekday of grace.
    assert brief("exchange:NSE") == ("market_data", "2026-11-04", "weekdays", 1, "on_time", None)
    assert brief("fx") == ("fx", "2026-11-05", "weekdays", 1, "on_time", None)

    assert body["overdue_count"] == 4
    # Overdue rows first.
    assert [row["overdue"] for row in body["sources"]] == [True] * 4 + [False] * 6
    assert rows["account:14"]["platform"] == "SHAREKHAN"


def test_weekend_and_late_quotes_on_the_endpoint(client, db_engine, monkeypatch):
    monkeypatch.setenv("STOCK_EXCHANGES", "NSE")
    _seed_sources(db_engine)
    # Wednesday's close is on time through Friday (one weekday of grace), not over the weekend.
    _freeze_today(monkeypatch, SAT)
    rows = _by_key(client.get("/dashboard/source-freshness").json())
    assert rows["exchange:NSE"]["status"] == "overdue"
    assert rows["exchange:NSE"]["due_date"] == "2026-11-06"
    assert rows["exchange:NSE"]["days_overdue"] == 1
    # Thursday's FX is fine all weekend and on Monday.
    for today in (SAT, SUN, MON):
        clear_shared_cache()
        _freeze_today(monkeypatch, today)
        rows = _by_key(client.get("/dashboard/source-freshness").json())
        assert rows["fx"]["status"] == "on_time", today
    clear_shared_cache()
    _freeze_today(monkeypatch, TUE)
    assert _by_key(client.get("/dashboard/source-freshness").json())["fx"]["days_overdue"] == 1


def test_a_user_with_no_sources_has_no_rows(client, db_engine, monkeypatch):
    _freeze_today(monkeypatch)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO fx_rates (rate_date, base, quote, rate, source) "
                "VALUES ('2026-11-05', 'EUR', 'SGD', 1.5, 'frankfurter')"
            )
        )
    body = client.get("/dashboard/source-freshness").json()
    assert body["sources"] == [] and body["overdue_count"] == 0


def test_override_changes_the_cadence_and_reset_restores_the_default(client, db_engine, monkeypatch):
    _freeze_today(monkeypatch)
    _seed_sources(db_engine)

    resp = client.put("/dashboard/source-freshness/account:14", json={"cadence": "quarterly", "grace_days": 5})
    assert resp.status_code == 200, resp.text
    row = resp.json()
    # 6 Sep + 3 months + 5 days = 11 Dec: on time.
    assert (row["cadence"], row["grace_days"], row["overridden"], row["status"], row["due_date"]) == (
        "quarterly", 5, True, "on_time", "2026-12-11",
    )
    assert (row["default_cadence"], row["default_grace_days"]) == ("monthly", 10)
    body = client.get("/dashboard/source-freshness").json()
    assert _by_key(body)["account:14"]["overridden"] is True
    assert body["overdue_count"] == 3

    # Off: the never-loaded bank stops counting.
    client.put("/dashboard/source-freshness/account:16", json={"cadence": "off", "grace_days": 0})
    body = client.get("/dashboard/source-freshness").json()
    assert _by_key(body)["account:16"]["status"] == "no_schedule"
    assert body["overdue_count"] == 2

    # Editing again updates the same row.
    client.put("/dashboard/source-freshness/account:14", json={"cadence": "weekly", "grace_days": 0})
    assert _by_key(client.get("/dashboard/source-freshness").json())["account:14"]["cadence"] == "weekly"
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM source_freshness_overrides")).scalar_one() == 2

    resp = client.delete("/dashboard/source-freshness/account:14")
    assert resp.status_code == 200
    assert (resp.json()["cadence"], resp.json()["overridden"], resp.json()["status"]) == ("monthly", False, "overdue")
    assert _by_key(client.get("/dashboard/source-freshness").json())["account:14"]["overridden"] is False


def test_override_validation_and_owner_scope(client, db_engine, monkeypatch):
    _freeze_today(monkeypatch)
    _seed_sources(db_engine)
    bad = client.put("/dashboard/source-freshness/account:11", json={"cadence": "hourly", "grace_days": 1})
    assert bad.status_code == 422
    assert client.put("/dashboard/source-freshness/account:11", json={"cadence": "daily", "grace_days": 91}).status_code == 422
    # Another user's account, a closed account and an unknown key are not the caller's sources.
    for key in ("account:18", "account:17", "exchange:US", "nonsense"):
        assert client.put(f"/dashboard/source-freshness/{key}", json={"cadence": "daily", "grace_days": 1}).status_code == 404
        assert client.delete(f"/dashboard/source-freshness/{key}").status_code == 404

    # The other user sees only their own bank, and none of the caller's overrides.
    client.put("/dashboard/source-freshness/fx", json={"cadence": "off", "grace_days": 0})
    other = client.get("/dashboard/source-freshness", headers=auth_headers(OTHER_USER)).json()
    assert [row["source_key"] for row in other["sources"]] == ["account:18", "fx"]
    assert _by_key(other)["fx"]["overridden"] is False
    assert client.put(
        "/dashboard/source-freshness/account:11", json={"cadence": "daily", "grace_days": 1}, headers=auth_headers(OTHER_USER)
    ).status_code == 404


def test_anonymous_calls_are_refused(anon_client):
    assert anon_client.get("/dashboard/source-freshness").status_code == 401
    assert anon_client.put("/dashboard/source-freshness/fx", json={"cadence": "off", "grace_days": 0}).status_code == 401


# ─── The canonical dates match the Accounts page's ───────────────────────────


@pytest.mark.parametrize("scenario", ["mid", "first"])
def test_account_dates_match_account_data_status_on_the_household(db_engine, monkeypatch, scenario):
    """Same canonical facts as ``account_data_status`` (the Accounts page's
    "last data" date), at several anchors; the only difference is a card statement
    older than valuation's 45 days, which freshness still reports."""
    now = SCENARIOS[scenario]
    household_env(monkeypatch, now)
    build_household(db_engine, now=now)
    today = now.astimezone(SGT).date()
    with Session(db_engine) as db:
        for anchor in (today, today - timedelta(days=20), date(today.year, today.month, 1), today - timedelta(days=75)):
            clear_shared_cache()
            dates = {
                int(r["account_id"]): _date_only(r["as_of_date"])
                for r in canonical_latest_fact_dates(db, current_user_id=USER_A, anchor_date=anchor)
            }
            status = account_data_status(
                db,
                current_user_id=USER_A,
                anchor_ts=datetime(anchor.year, anchor.month, anchor.day, tzinfo=SGT),
                month_start=date(anchor.year, anchor.month, 1),
            )
            expected = {account_id: date.fromisoformat(s["last_data_as_of"]) for account_id, s in status.items()}
            assert dates, anchor
            for account_id, as_of in dates.items():
                if account_id in expected:
                    assert as_of == expected[account_id], (anchor, account_id)
                else:
                    # Only a card statement past valuation's age limit is extra.
                    assert (anchor - as_of).days > 45, (anchor, account_id)
            assert set(expected) <= set(dates), anchor
