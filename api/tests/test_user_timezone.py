"""Per-user home timezone and server-side base currency (#202).

Month logic (which month is open, when an anchor passes, History completion,
the card-transaction month boundary) follows each user's own timezone; quote
and FX dates don't (D-44). Synthetic users and data only.
"""
from __future__ import annotations

import threading
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import valuation_cache
from app.core import clock as core_clock
from app.valuation.clock import _anchor_ts, _parse_month
from app.valuation.facts import _credit_card_liability_component
from app.valuation.history import refresh_dirty_wealth_rollups
from app.wealth_rollup_dirty import dirty_state, mark_rollups_dirty
from tests.test_auth import _insert_user_with_password
from tests.valuation_household import (
    NEW_YORK,
    SCENARIOS,
    USER_A,
    USER_B,
    as_user,
    build_household,
    freeze_clock,
    household_env,
    set_user_timezone,
)

FIRST = SCENARIOS["first"]  # 2026-04-01 06:00 SGT = 2026-03-31 18:00 New York
SINGAPORE = "Asia/Singapore"
TOL = 0.01


def _get(client: TestClient, path: str) -> dict:
    resp = client.get(path)
    assert resp.status_code == 200, (path, resp.text)
    return resp.json()


def _summary(client: TestClient, month: str) -> dict:
    return _get(client, f"/dashboard/summary?month={month}&base_currency=SGD&compare=prev_month,prev_year")


def _timeline_months(client: TestClient) -> list[str]:
    resp = client.post("/dashboard/net-worth-timeline/backfill?months=6&base_currency=SGD")
    assert resp.status_code == 200, resp.text
    return [p["month"] for p in _get(client, "/dashboard/net-worth-timeline?months=6&base_currency=SGD")["points"]]


# ─── Two users, one instant ──────────────────────────────────────────────────


@pytest.fixture()
def two_timezones(client: TestClient, db_engine, monkeypatch):
    """The household at the "first" instant; user A lives in Singapore, user B
    in New York."""
    household_env(monkeypatch, FIRST)
    build_household(db_engine, now=FIRST)
    set_user_timezone(db_engine, USER_A, SINGAPORE)
    set_user_timezone(db_engine, USER_B, NEW_YORK)
    return client


def _open_and_completed(client: TestClient, monkeypatch, user_id: int) -> dict:
    as_user(monkeypatch, user_id)
    april = _summary(client, "2026-04")
    march = _summary(client, "2026-03")
    return {
        "april_boundary": april["net_worth_boundary_at"],
        "march_boundary": march["net_worth_boundary_at"],
        "live_compare_month": march["current_net_worth_change"]["vs_prev_month"]["compare_month"],
        "march_is_live": {
            path: _get(client, f"{path}?month=2026-03&base_currency=SGD")["is_live"]
            for path in ("/dashboard/stock-holdings", "/dashboard/cash-deposits", "/crypto/summary")
        },
        "history": _timeline_months(client),
    }


def test_two_users_at_the_same_instant_see_their_own_months(two_timezones, monkeypatch):
    """06:00 on 1 April in Singapore is 18:00 on 31 March in New York: A's
    March is completed and April open; B's March is still open, February their
    latest completed month. Asked alternately, with the shared cache on."""
    a = _open_and_completed(two_timezones, monkeypatch, USER_A)
    b = _open_and_completed(two_timezones, monkeypatch, USER_B)
    a_again = _open_and_completed(two_timezones, monkeypatch, USER_A)

    assert a == a_again
    assert a["march_boundary"] == "2026-04-01T00:00:00+00:00"
    assert a["live_compare_month"] == "2026-03"
    assert a["march_is_live"] == {k: False for k in a["march_is_live"]}
    assert a["history"][-1] == "2026-03"

    assert b["march_boundary"] == "2026-03-01T00:00:00+00:00"
    assert b["live_compare_month"] == "2026-02"
    assert b["march_is_live"] == {k: True for k in b["march_is_live"]}
    assert b["history"][-1] == "2026-02"
    assert "2026-03" not in b["history"]


def test_us_household_dashboard_and_history_agree(client: TestClient, db_engine, monkeypatch):
    """The first_us moment: the open month reports February's month-end, and
    History's newest point is that same month with the same figures."""
    household_env(monkeypatch, FIRST)
    build_household(db_engine, now=FIRST, timezone_name=NEW_YORK)
    march = _summary(client, "2026-03")
    _timeline_months(client)
    points = _get(client, "/dashboard/net-worth-timeline?months=6&base_currency=SGD")["points"]
    newest = points[-1]
    assert newest["month"] == "2026-02"
    assert march["net_worth_boundary_at"][:10] == newest["anchor_date"] == "2026-03-01"
    point = {k: newest[k] for k in ("cash", "stocks_funds", "crypto", "liabilities", "total")}
    assert point == pytest.approx(march["net_worth"], abs=TOL)
    # March's card spending is the open month's live liability.
    assert march["current_net_worth"]["liabilities"] > 0


def test_changing_timezone_moves_the_open_month(two_timezones, monkeypatch, db_engine):
    """User A moves to New York (Settings): from the next request on, March is
    open again for them, and nothing cached under Singapore is served."""
    as_user(monkeypatch, USER_A)
    assert _summary(two_timezones, "2026-03")["net_worth_boundary_at"] == "2026-04-01T00:00:00+00:00"
    resp = two_timezones.patch("/auth/preferences", json={"timezone": NEW_YORK})
    assert resp.status_code == 200, resp.text
    assert resp.json()["timezone"] == NEW_YORK
    assert _summary(two_timezones, "2026-03")["net_worth_boundary_at"] == "2026-03-01T00:00:00+00:00"


def test_cache_stamp_includes_the_timezone(monkeypatch):
    freeze_clock(monkeypatch, FIRST)
    with core_clock.use_timezone(SINGAPORE):
        singapore = valuation_cache._day_stamp()
    with core_clock.use_timezone(NEW_YORK):
        new_york = valuation_cache._day_stamp()
    assert singapore[1:] == (SINGAPORE, date(2026, 4, 1))
    assert new_york[1:] == (NEW_YORK, date(2026, 3, 31))


# ─── Card-transaction month boundary ─────────────────────────────────────────


def _seed_card(db_engine, user_id: int) -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, username, is_active, is_admin, created_at, updated_at) "
                "VALUES (:u, :n, 1, 0, '2026-01-01 00:00:00+00:00', '2026-01-01 00:00:00+00:00')"
            ),
            {"u": user_id, "n": f"card-user-{user_id}"},
        )
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, user_id, account_type, currency) "
                "VALUES (:id, 'Synthetic Card', 'SYNTH', :u, 'CREDIT_CARD', 'SGD')"
            ),
            {"id": 9100 + user_id, "u": user_id},
        )
        conn.execute(
            text(
                "INSERT INTO transactions (ts, account_id, amount, type, currency) VALUES (:ts, :a, :amt, 'EXPENSE', 'SGD')"
            ),
            [
                # 03:00Z on 1 Feb: 11:00 on 1 Feb in Singapore, 22:00 on 31 Jan in New York.
                {"ts": "2026-02-01 03:00:00+00:00", "a": 9100 + user_id, "amt": -100.0},
                # Date-only (a statement row): 1 Feb, in every timezone.
                {"ts": "2026-02-01 00:00:00+00:00", "a": 9100 + user_id, "amt": -20.0},
                # 03:00Z on 1 Mar: 1 Mar in Singapore, 28 Feb (22:00) in New York.
                {"ts": "2026-03-01 03:00:00+00:00", "a": 9100 + user_id, "amt": -3.0},
                # Date-only: 1 Mar, in every timezone.
                {"ts": "2026-03-01 00:00:00+00:00", "a": 9100 + user_id, "amt": -7000.0},
            ],
        )


@pytest.mark.parametrize(
    ("timezone_name", "expected"),
    [
        # February = [1 Feb, 1 Mar) by the user's calendar.
        (SINGAPORE, 120.0),  # 1 Feb 11:00 + 1 Feb (date-only)
        (NEW_YORK, 23.0),  # 1 Feb (date-only) + 28 Feb 22:00
        ("UTC", 120.0),  # the old rule's 00:00 UTC boundaries
    ],
)
def test_card_month_boundary_is_midnight_in_the_users_timezone(db_engine, monkeypatch, timezone_name, expected):
    monkeypatch.setenv("SNAPSHOT_DAY", "1")
    _seed_card(db_engine, 77)
    anchor = _anchor_ts(_parse_month("2026-02"))
    with Session(db_engine) as db, core_clock.use_timezone(timezone_name):
        liability, cards = _credit_card_liability_component(db, anchor, "SGD", 77)
    assert cards == {9177}
    assert liability == pytest.approx(expected, abs=TOL)


def test_live_card_window_counts_a_date_only_row_dated_today(db_engine, monkeypatch):
    """Live "now" (18:00 on 31 March in New York): the window is March by the
    user's calendar, and a date-only row dated 1 March counts."""
    monkeypatch.setenv("SNAPSHOT_DAY", "1")
    _seed_card(db_engine, 78)
    now_ny = FIRST.astimezone(core_clock.ZoneInfo(NEW_YORK))
    with Session(db_engine) as db, core_clock.use_timezone(NEW_YORK):
        liability, _cards = _credit_card_liability_component(db, now_ny, "SGD", 78)
    # 1 Mar (date-only) only: 28 Feb 22:00 local is February.
    assert liability == pytest.approx(7000.0, abs=TOL)


# ─── Dirty marks and background History refresh ──────────────────────────────


def test_dirty_marks_use_each_users_timezone(two_timezones, db_engine):
    """A change dated 31 March can touch Singapore's stored March row (that
    month is completed there) but none of New York's (their latest completed
    anchor is 1 March)."""
    with Session(db_engine) as db:
        # Building the household left marks of its own.
        db.execute(text("DELETE FROM wealth_rollup_dirty WHERE user_id IN (:a, :b)"), {"a": USER_A, "b": USER_B})
        assert mark_rollups_dirty(db, date(2026, 3, 31), user_ids=[USER_A, USER_B], reason="test") is True
        db.commit()
        assert dirty_state(db, USER_A)[0] == date(2026, 3, 31)
        assert dirty_state(db, USER_B)[0] is None


def test_background_refresh_runs_each_user_in_their_timezone(two_timezones, monkeypatch, db_engine):
    """A's History is stored through March (Singapore). A then moves to New York
    and a job refreshes the dirty History outside any request: in New York March
    isn't completed yet, so its stored row goes."""
    as_user(monkeypatch, USER_A)
    assert _timeline_months(two_timezones)[-1] == "2026-03"
    set_user_timezone(db_engine, USER_A, NEW_YORK)
    with Session(db_engine) as db:
        assert mark_rollups_dirty(db, date(2026, 1, 1), user_ids=[USER_A], reason="test") is True
        db.commit()
        refresh_dirty_wealth_rollups(db)
        months = [
            row[0]
            for row in db.execute(
                text("SELECT month FROM wealth_monthly_rollups WHERE user_id = :u ORDER BY month"), {"u": USER_A}
            ).fetchall()
        ]
    assert months[-1] == "2026-02"


def test_timezone_change_marks_history_from_the_first_card_transaction(client: TestClient, db_engine, monkeypatch):
    _seed_card(db_engine, 79)
    monkeypatch.setenv("AUTH_BYPASS_USER_ID", "79")
    monkeypatch.setenv("AUTH_ALLOW_LEGACY_NULL_OWNERSHIP", "0")
    resp = client.patch("/auth/preferences", json={"timezone": NEW_YORK})
    assert resp.status_code == 200, resp.text
    with Session(db_engine) as db:
        from_date, generation = dirty_state(db, 79)
    assert from_date == date(2026, 2, 1)
    assert generation == 1

    # The same timezone again changes nothing.
    assert client.patch("/auth/preferences", json={"timezone": NEW_YORK}).status_code == 200
    with Session(db_engine) as db:
        assert dirty_state(db, 79)[1] == 1


# ─── Preferences API ─────────────────────────────────────────────────────────


def _login_env(monkeypatch) -> None:
    monkeypatch.delenv("AUTH_BYPASS_USER_ID", raising=False)
    monkeypatch.setenv("AUTH_ALLOW_LEGACY_NULL_OWNERSHIP", "0")
    monkeypatch.setenv("AUTH_ACCESS_TOKEN_SECRET", "test-access-secret")
    monkeypatch.setenv("TZ", SINGAPORE)


def _login(client: TestClient, username: str, password: str) -> tuple[dict, dict]:
    resp = client.post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return body, {"Authorization": f"Bearer {body['access_token']}"}


def test_new_user_timezone_is_unset_until_filled(client: TestClient, db_engine, monkeypatch):
    _login_env(monkeypatch)
    _insert_user_with_password(db_engine, user_id=2201, username="tz_new_user", password="TzNewPass1!")
    body, headers = _login(client, "tz_new_user", "TzNewPass1!")
    prefs = body["preferences"]
    assert prefs["timezone"] == SINGAPORE  # the app TZ meanwhile
    assert prefs["timezone_source"] == "unset"
    assert prefs["base_currency"] is None

    resp = client.patch("/auth/preferences", json={"timezone": NEW_YORK, "base_currency": "usd"}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "theme": "dark",
        "accent_color": "#0f7a5c",
        "timezone": NEW_YORK,
        "timezone_source": "user",
        "base_currency": "USD",
    }
    # Persisted, and on the refresh payload too (D-26).
    assert client.get("/auth/preferences", headers=headers).json() == resp.json()
    refreshed = client.post("/auth/refresh")
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["preferences"] == resp.json()


def test_existing_user_follows_the_app_timezone(client: TestClient, db_engine, monkeypatch):
    """An account from before #202 (migration 077 sets timezone_from_app)."""
    _login_env(monkeypatch)
    monkeypatch.setenv("TZ", "Europe/London")
    _insert_user_with_password(db_engine, user_id=2202, username="tz_old_user", password="TzOldPass1!")
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO user_preferences (user_id, theme, accent_color, timezone_from_app, updated_at) "
                "VALUES (2202, 'light', '#2b6ddb', 1, '2026-01-01 00:00:00+00:00')"
            )
        )
    body, headers = _login(client, "tz_old_user", "TzOldPass1!")
    assert body["preferences"]["timezone"] == "Europe/London"
    assert body["preferences"]["timezone_source"] == "app"
    # Theme/accent PATCHes leave that alone.
    resp = client.patch("/auth/preferences", json={"theme": "dark"}, headers=headers)
    assert resp.json()["timezone_source"] == "app"
    resp = client.patch("/auth/preferences", json={"timezone": "Europe/London"}, headers=headers)
    assert resp.json()["timezone_source"] == "user"


@pytest.mark.parametrize(
    "patch",
    [
        {"timezone": "Mars/Olympus_Mons"},
        {"timezone": "../../etc/passwd"},
        {"timezone": "/usr/share/zoneinfo/UTC"},
        {"timezone": ""},
        {"base_currency": "EUR"},
        {"base_currency": "S$"},
    ],
)
def test_invalid_timezone_or_base_currency_is_refused(client: TestClient, patch: dict, monkeypatch):
    monkeypatch.setenv("AUTH_BYPASS_USER_ID", "2203")
    resp = client.patch("/auth/preferences", json=patch)
    assert resp.status_code == 422, resp.text


# ─── The clock ───────────────────────────────────────────────────────────────


def test_timezone_names_are_validated():
    assert core_clock.normalize_timezone_name(" America/New_York ") == NEW_YORK
    assert core_clock.normalize_timezone_name("UTC") == "UTC"
    for bad in (None, "", "Nowhere/City", "../etc", "/etc/localtime", 42):
        assert core_clock.normalize_timezone_name(bad) is None


def test_request_timezone_bound_in_a_thread_holds_for_the_request():
    """FastAPI runs sync dependencies in a threadpool, each in a copy of the
    context: the slot set by the middleware is shared, so the endpoint sees the
    timezone the auth dependency bound."""
    import contextvars

    seen: list[str] = []
    token = core_clock._slot.set(core_clock._TimezoneSlot())
    try:
        ctx = contextvars.copy_context()
        worker = threading.Thread(target=ctx.run, args=(core_clock.bind_request_timezone, NEW_YORK))
        worker.start()
        worker.join()
        seen.append(core_clock.current_timezone_name())
    finally:
        core_clock._slot.reset(token)
    assert seen == [NEW_YORK]
    assert core_clock.current_timezone_name() == core_clock.default_timezone_name()


def test_app_today_follows_the_bound_timezone():
    instant = datetime(2026, 3, 31, 22, 0, tzinfo=timezone.utc)
    with core_clock.use_timezone(SINGAPORE):
        assert core_clock.app_today(instant) == date(2026, 4, 1)
    with core_clock.use_timezone(NEW_YORK):
        assert core_clock.app_today(instant) == date(2026, 3, 31)
    with core_clock.use_timezone("not/a-zone"):
        assert core_clock.current_timezone_name() == core_clock.default_timezone_name()
