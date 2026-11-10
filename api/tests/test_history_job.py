"""History first run in the background (#292, D-89): the run's progress, past FX rates
fetched once and capped before the months (each month then uses stored rates only),
the default range = the span of the user's data, one run at a time, failures shown."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

from app import fx
from app.valuation import history_job
from tests.canonical_test_helpers import seed_canonical_account_balance_for_test, seed_canonical_position_snapshot_for_test

NOW = datetime(2026, 7, 13, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clean_runs(monkeypatch):
    monkeypatch.setenv("SNAPSHOT_DAY", "1")
    monkeypatch.setattr("app.valuation.clock._current_anchor_ts", lambda: NOW)
    monkeypatch.setattr("app.valuation.fx.get_rates", lambda *_a, **_k: {"SGD": 1.0, "USD": 1.0})
    history_job._RUNS.clear()
    history_job._THREADS.clear()
    yield
    for key in list(history_job._THREADS):
        history_job.wait(*key)
    history_job._RUNS.clear()
    history_job._THREADS.clear()


def _seed_account(db_engine, *, account_id: int = 970, as_of: date = date(2026, 4, 20)) -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, user_id, account_type, currency, country) VALUES "
                "(:id, 'IBKR account', 'IBKR', 1, 'BROKER', 'SGD', 'SG')"
            ),
            {"id": account_id},
        )
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(:id, 'HJ292', 'HJ292', 'STOCK', 'SGD', 'SG')"
            ),
            {"id": account_id},
        )
    seed_canonical_position_snapshot_for_test(
        db_engine, account_id=account_id, asset_id=account_id, as_of=as_of,
        quantity=2, market_value_base=4000.0, market_price=2000.0, platform_code="IBKR",
    )


def _rows(db_engine) -> list[str]:
    with db_engine.connect() as conn:
        return [
            str(r[0])
            for r in conn.execute(
                text("SELECT month FROM wealth_monthly_rollups WHERE user_id = 1 AND base_currency = 'SGD' ORDER BY month")
            )
        ]


def test_status_is_idle_before_any_run(client):
    resp = client.get("/dashboard/net-worth-timeline/generate/status?base_currency=SGD")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "idle"
    assert body["started_at"] is None


def test_generate_runs_in_the_background_and_reports_progress(client, db_engine):
    _seed_account(db_engine)
    seen: list[tuple[int, int, str]] = []
    original = history_job._update

    def _spy(run, **changes):
        original(run, **changes)
        if "months_done" in changes and "current_month" in changes and changes["current_month"]:
            seen.append((changes["months_done"], run.months_total, changes["current_month"]))

    history_job._update = _spy
    try:
        resp = client.post("/dashboard/net-worth-timeline/generate?months=3&base_currency=SGD")
        assert resp.status_code == 200
        assert resp.json()["status"] in {"running", "completed"}
        history_job.wait(1, "SGD")
    finally:
        history_job._update = original

    body = client.get("/dashboard/net-worth-timeline/generate/status?base_currency=SGD").json()
    assert body["status"] == "completed"
    assert body["stage"] == "done"
    assert body["months"] == 3
    assert body["months_total"] == 3 and body["months_done"] == 3
    assert body["months_written"] == 2  # May, June; July is open
    assert body["fx"]["status"] in {"up_to_date", "completed"}  # tests' synthetic provider
    assert [s[0] for s in seen] == [0, 1, 2]
    assert [s[2] for s in seen] == ["2026-05", "2026-06", "2026-07"]
    assert _rows(db_engine) == ["2026-05", "2026-06"]
    with db_engine.connect() as conn:
        job = conn.execute(text("SELECT status, user_id FROM job_runs WHERE job = 'history_generate'")).fetchall()
    assert [(r[0], r[1]) for r in job] == [("success", 1)]


def test_default_range_is_the_span_of_the_data(client, db_engine):
    _seed_account(db_engine, as_of=date(2026, 3, 2))
    timeline = client.get("/dashboard/net-worth-timeline?months=24&base_currency=SGD").json()
    assert timeline["data_span"] == {"first_month": "2026-03", "months": 5}

    assert client.post("/dashboard/net-worth-timeline/generate?base_currency=SGD").status_code == 200
    history_job.wait(1, "SGD")
    body = history_job.status(1, "SGD")
    assert body["months"] == 5
    assert _rows(db_engine) == ["2026-03", "2026-04", "2026-05", "2026-06"]


def test_data_span_counts_wallet_snapshots_and_is_capped(db_engine):
    from sqlalchemy.orm import Session

    db = Session(bind=db_engine)
    try:
        assert history_job.history_span(db, 1) is None
        with db_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO crypto_wallets (id, chain_type, chain, address, status, created_at, user_id) "
                    "VALUES (2920, 'evm', 'ethereum', '0xhj292', 'active', '2020-01-01', 1)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO crypto_wallet_snapshots (id, wallet_id, as_of_date, fetched_at, total_usd) "
                    "VALUES (2920, 2920, '2025-11-03', '2025-11-03', 10)"
                )
            )
        assert history_job.history_span(db, 1) == {"first_month": "2025-11", "months": 9}
        with db_engine.begin() as conn:
            conn.execute(text("UPDATE crypto_wallet_snapshots SET as_of_date = '2001-01-05' WHERE id = 2920"))
        assert history_job.history_span(db, 1) == {"first_month": "2001-01", "months": 120}
        assert history_job.history_span(db, 2) is None  # another user's data isn't counted
    finally:
        db.close()


def test_fx_is_fetched_once_capped_then_months_use_stored_rates_only(client, db_engine, monkeypatch):
    """The cap: one back-fill (itself capped, #290) before the months, and no provider
    call while the months are valued, even for a foreign-currency balance."""
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, user_id, account_type, currency, country) VALUES "
                "(971, 'USD account', 'DBS', 1, 'BANK', 'USD', 'SG')"
            )
        )
    seed_canonical_account_balance_for_test(db_engine, account_id=971, as_of=date(2026, 4, 2), currency="USD", balance_base=100.0)
    backfills: list[int] = []
    monkeypatch.setattr(
        "app.fx_backfill.run_backfill",
        lambda _db, user_id, _base, **_k: backfills.append(user_id) or {
            "status": "partial", "fetched_requests": 12, "failed_requests": 0, "remaining_requests": 3,
            "unsupported_currencies": [],
        },
    )
    provider_calls: list[tuple] = []
    monkeypatch.setattr(fx, "fill_rates", lambda *a, **k: provider_calls.append(a) or {})
    remote_during_months: list[bool] = []
    original_refresh = history_job._refresh_wealth_rollups

    def _refresh(*a, **k):
        remote_during_months.append(fx.provider_allowed())
        return original_refresh(*a, **k)

    monkeypatch.setattr(history_job, "_refresh_wealth_rollups", _refresh)

    assert client.post("/dashboard/net-worth-timeline/generate?months=4&base_currency=SGD").status_code == 200
    history_job.wait(1, "SGD")
    body = history_job.status(1, "SGD")
    assert body["status"] == "completed"
    assert backfills == [1]
    assert body["fx"]["status"] == "partial" and body["fx"]["remaining_requests"] == 3
    assert remote_during_months == [False]
    assert provider_calls == []
    assert fx.provider_allowed() is True  # only the run's own context reads stored rates only


def test_stored_rates_only_switches_the_provider_off_inside_its_context():
    assert fx.provider_allowed()
    with fx.stored_rates_only():
        assert not fx.provider_allowed()
    assert fx.provider_allowed()


def test_a_running_run_is_returned_instead_of_starting_another(client):
    run = history_job.HistoryRun(1, "SGD", 7)
    history_job._RUNS[(1, "SGD")] = run
    resp = client.post("/dashboard/net-worth-timeline/generate?months=3&base_currency=SGD")
    assert resp.status_code == 200
    assert resp.json()["months"] == 7
    assert resp.json()["started_at"] == run.started_at.isoformat()
    assert (1, "SGD") not in history_job._THREADS


def test_a_failed_run_says_so(client, monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(history_job, "_refresh_wealth_rollups", _boom)
    assert client.post("/dashboard/net-worth-timeline/generate?months=2&base_currency=SGD").status_code == 200
    history_job.wait(1, "SGD")
    body = client.get("/dashboard/net-worth-timeline/generate/status?base_currency=SGD").json()
    assert body["status"] == "failed"
    assert "Try again" in body["error"]
    assert "boom" not in body["error"]


def test_runs_are_per_user(db_engine):
    from tests.auth_helpers import signed_in_client

    history_job._RUNS[(1, "SGD")] = history_job.HistoryRun(1, "SGD", 7)
    other = signed_in_client(db_engine, 2)
    assert other.get("/dashboard/net-worth-timeline/generate/status?base_currency=SGD").json()["status"] == "idle"
