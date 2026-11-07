"""FX back-fill (#290, D-75): the span of a user's data, skipping stored dates, the
request cap, idempotence, History marked dirty, and admin-only. Providers are
always fakes (conftest blocks real HTTP)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import fx, fx_backfill
from app.wealth_rollup_dirty import dirty_state
from tests.auth_helpers import signed_in_client
from tests.canonical_test_helpers import seed_canonical_account_balance_for_test
from tests.fx_test_helpers import SYNTHETIC_FX_PER_EUR

TODAY = date(2026, 3, 10)


def _seed_user_data(db_engine, *, user_id: int = 1, account_id: int = 501, start=date(2026, 1, 5), end=date(2026, 2, 20)):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, user_id) "
                "VALUES (:id, 'Synthetic USD account', 'DBS', 'BANK', 'USD', 'SG', :uid)"
            ),
            {"id": account_id, "uid": user_id},
        )
        conn.execute(
            text(
                "INSERT INTO transactions (id, ts, account_id, amount, type, currency, category) "
                "VALUES (:id, :ts, :acc, -12.5, 'EXPENSE', 'HKD', 'Food')"
            ),
            {"id": account_id * 10, "ts": datetime(end.year, end.month, end.day, tzinfo=timezone.utc), "acc": account_id},
        )
    seed_canonical_account_balance_for_test(db_engine, account_id=account_id, as_of=start, currency="USD", balance_base=100.0)


def _store_frankfurter(db_engine, days):
    with db_engine.begin() as conn:
        for day in days:
            for quote, rate in SYNTHETIC_FX_PER_EUR.items():
                conn.execute(
                    text(
                        "INSERT INTO fx_rates (rate_date, base, quote, rate, source, fetched_at) "
                        "VALUES (:d, 'EUR', :q, :r, 'frankfurter', '2026-01-01T00:00:00+00:00')"
                    ),
                    {"d": day.isoformat(), "q": quote, "r": rate},
                )


def _weekdays(start: date, end: date):
    day = start
    while day <= end:
        if day.weekday() < 5:
            yield day
        day += timedelta(days=1)


@pytest.fixture()
def calls(monkeypatch):
    """A fake Frankfurter that answers every weekday of the range, counting calls."""
    seen: list[tuple[date, date]] = []

    def fake(start, end):
        seen.append((start, end))
        return {day: dict(SYNTHETIC_FX_PER_EUR) for day in _weekdays(start, end)}

    monkeypatch.setattr(fx, "_fetch_frankfurter", fake)
    return seen


def _db(db_engine) -> Session:
    return Session(bind=db_engine)


def test_span_is_the_users_own_dated_facts(db_engine):
    _seed_user_data(db_engine, user_id=1, account_id=501)
    _seed_user_data(db_engine, user_id=2, account_id=502, start=date(2020, 1, 1), end=date(2026, 3, 1))
    db = _db(db_engine)
    try:
        assert fx_backfill.data_span(db, 1) == (date(2026, 1, 5), date(2026, 2, 20))
        assert fx_backfill.held_currencies(db, 1, "SGD") == ["HKD", "SGD", "USD"]
        assert fx_backfill.data_span(db, 99) is None
    finally:
        db.close()


def test_plan_covers_the_span_from_one_lookback_early_newest_first(db_engine):
    _seed_user_data(db_engine)
    db = _db(db_engine)
    try:
        plan = fx_backfill.plan_backfill(db, 1, "SGD", today=TODAY)
    finally:
        db.close()
    # 7-day lookback before 5 Jan is 29 Dec 2025 (a Monday); the span ends 20 Feb.
    assert plan.requests == [(date(2025, 12, 29), date(2026, 2, 20))]
    assert plan.remaining_requests == 0
    assert plan.uncovered_days == len(list(_weekdays(date(2025, 12, 29), date(2026, 2, 20))))


def test_stored_days_are_skipped_and_a_second_run_fetches_nothing(db_engine, calls, monkeypatch):
    _seed_user_data(db_engine)
    # January is already stored: only February is fetched.
    _store_frankfurter(db_engine, _weekdays(date(2025, 12, 22), date(2026, 1, 31)))
    db = _db(db_engine)
    try:
        first = fx_backfill.run_backfill(db, 1, "SGD", today=TODAY)
        assert first["status"] == "completed"
        assert calls == [(date(2026, 2, 2), date(2026, 2, 20))]
        assert first["rows_stored"] > 0

        second = fx_backfill.run_backfill(db, 1, "SGD", today=TODAY)
        assert second["status"] == "up_to_date"
        assert second["planned_requests"] == []
        assert len(calls) == 1  # idempotent: nothing asked again
    finally:
        db.close()


def test_weekends_and_short_holidays_count_as_covered_but_the_tail_does_not():
    # Rows on Thu 2 Apr and Tue 7 Apr 2026 (Good Friday and Easter Monday closed):
    # Fri 3 and Mon 6 sit in a 5-day hole between stored rows, so they're covered.
    stored = {date(2026, 4, 2), date(2026, 4, 7)}
    assert fx_backfill.uncovered_days(date(2026, 4, 2), date(2026, 4, 7), stored) == []
    # After the last stored row nothing is covered, however recent that row is.
    assert fx_backfill.uncovered_days(date(2026, 4, 8), date(2026, 4, 10), stored) == [
        date(2026, 4, 8), date(2026, 4, 9), date(2026, 4, 10)
    ]
    # A long hole (a week and more) is a gap, not a holiday.
    assert date(2026, 4, 20) in fx_backfill.uncovered_days(date(2026, 4, 20), date(2026, 4, 20), {date(2026, 4, 14), date(2026, 4, 24)})


def test_requests_are_capped_and_the_rest_reported(db_engine, monkeypatch):
    _seed_user_data(db_engine, start=date(2021, 1, 4), end=date(2026, 2, 20))
    monkeypatch.setenv("FX_BACKFILL_MAX_REQUESTS", "2")
    db = _db(db_engine)
    try:
        plan = fx_backfill.plan_backfill(db, 1, "SGD", today=TODAY)
    finally:
        db.close()
    assert len(plan.requests) == 2
    assert plan.remaining_requests >= 3  # five years at 366 days a request
    assert plan.requests[0][1] == date(2026, 2, 20)  # newest first
    assert all((end - start).days < fx_backfill.MAX_DAYS_PER_REQUEST for start, end in plan.requests)


def test_new_past_rates_mark_history_dirty_from_their_earliest_date(db_engine, calls, monkeypatch):
    monkeypatch.setattr("app.wealth_rollup_dirty._utc_now", lambda: datetime(2026, 3, 10, tzinfo=timezone.utc))
    with db_engine.begin() as conn:
        conn.execute(text("INSERT INTO users (id, username, display_name, is_active) VALUES (1, 'fx-user', 'FX', 1)"))
    _seed_user_data(db_engine)
    db = _db(db_engine)
    try:
        assert dirty_state(db, 1) == (None, 0)
        fx_backfill.run_backfill(db, 1, "SGD", today=TODAY)
        assert dirty_state(db, 1)[0] == date(2025, 12, 29)
    finally:
        db.close()


def test_a_currency_the_provider_doesnt_publish_is_named(db_engine, calls):
    _seed_user_data(db_engine)
    with db_engine.begin() as conn:
        conn.execute(
            text("UPDATE transactions SET currency = 'ZZZ' WHERE account_id = 501")
        )
    db = _db(db_engine)
    try:
        result = fx_backfill.run_backfill(db, 1, "SGD", today=TODAY)
        assert result["unsupported_currencies"] == []  # nothing stored yet: can't tell
        again = fx_backfill.plan_backfill(db, 1, "SGD", today=TODAY).as_dict()
        assert again["unsupported_currencies"] == ["ZZZ"]
    finally:
        db.close()


def test_a_failed_range_is_counted_and_recorded_not_raised(db_engine, monkeypatch):
    _seed_user_data(db_engine)

    def down(*_a, **_k):
        raise RuntimeError("provider down")

    monkeypatch.setattr(fx, "_fetch_frankfurter", down)
    db = _db(db_engine)
    try:
        result = fx_backfill.run_backfill(db, 1, "SGD", today=TODAY)
        status = db.execute(text("SELECT status FROM job_runs WHERE job = 'fx_backfill'")).scalar()
    finally:
        db.close()
    assert result["status"] == "failed" and result["failed_requests"] == 1
    assert status == "failed"


def test_backfill_endpoint_is_admin_only_and_the_plan_is_readable_by_anyone(db_engine, client, calls):
    _seed_user_data(db_engine, user_id=1)
    member = signed_in_client(db_engine, 7, admin=False)
    assert member.post("/fx/backfill").status_code == 403
    plan = member.get("/fx/backfill-plan")
    assert plan.status_code == 200 and plan.json()["span_start"] is None  # user 7 has no data

    admin_plan = client.get("/fx/backfill-plan").json()
    assert admin_plan["span_start"] == "2026-01-05" and admin_plan["planned_requests"]
    ran = client.post("/fx/backfill")
    assert ran.status_code == 200 and ran.json()["status"] in {"completed", "partial"}
    assert calls


def test_data_hub_shows_the_backfill_job_once_it_has_run(db_engine, client, calls):
    def names():
        return [j["job"] for j in client.get("/dashboard/data-hub-summary").json()["job_status"]]

    assert "fx_backfill" not in names()
    _seed_user_data(db_engine)
    client.post("/fx/backfill")
    assert "fx_backfill" in names()


def test_no_background_backfill_while_remote_fx_is_off(monkeypatch):
    monkeypatch.setenv("FX_DISABLE_REMOTE", "1")
    assert fx_backfill.backfill_in_background(1) is None
    monkeypatch.setenv("FX_DISABLE_REMOTE", "0")
    monkeypatch.setenv("FX_BACKFILL_AFTER_IMPORT", "0")
    assert fx_backfill.backfill_in_background(1) is None
