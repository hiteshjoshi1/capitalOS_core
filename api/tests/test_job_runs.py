"""Job status (#156): job_runs rows, "done means the data advanced", per-account
IBKR due check, partial crypto retry, and the Data Hub status. Synthetic data only."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

import app.crypto.scheduler as crypto_scheduler
import app.market_data.scheduler as market_scheduler
import app.portfolio.scheduler as portfolio_scheduler
from app.core.job_runs import (
    FAILURE_THRESHOLD,
    JOB_CRYPTO,
    JOB_IBKR_FLEX,
    JOB_MARKET_DATA,
    job_status,
    record_job_run,
    safe_error_summary,
)
from app.crypto.adapters import NativeBalance
from app.crypto.refresh import refresh_wallet_snapshot_outcome

UTC = timezone.utc


def _runs(db_engine, job: str | None = None) -> list[dict]:
    sql = "SELECT * FROM job_runs" + (" WHERE job = :job" if job else "") + " ORDER BY id"
    with db_engine.connect() as conn:
        return [dict(row) for row in conn.execute(text(sql), {"job": job} if job else {}).mappings().all()]


def _record(db_engine, status: str, *, job=JOB_MARKET_DATA, scope="exchange:US", at=None, data_as_of=None, error=None):
    with Session(db_engine) as db:
        record_job_run(
            db,
            job=job,
            scope=scope,
            trigger="scheduled",
            status=status,
            started_at=at or datetime.now(tz=UTC),
            finished_at=at,
            data_as_of=data_as_of,
            data_advanced=status in ("success", "partial"),
            error=error,
        )


# --- error summaries ---------------------------------------------------------


def test_error_summary_drops_urls_tokens_addresses_and_account_numbers():
    exc = RuntimeError(
        "GET https://ndcdyn.example.com/Send?t=abcd1234efgh5678ijkl9012&q=998877&v=3 failed for U7654321 "
        "wallet 0x1111111111111111111111111111111111111111 token=s3cr3t-value api_key: zzz999"
    )
    summary = safe_error_summary(exc)
    assert summary.startswith("RuntimeError: ")
    for leaked in ("ndcdyn", "abcd1234", "998877", "U7654321", "0x1111", "s3cr3t", "zzz999"):
        assert leaked not in summary
    assert "[url]" in summary and "[account]" in summary and "[address]" in summary


def test_error_summary_keeps_readable_class_names_and_caps_length():
    assert safe_error_summary(RuntimeError("IbkrFlexImportInProgress for this account")) == (
        "RuntimeError: IbkrFlexImportInProgress for this account"
    )
    assert len(safe_error_summary("x " * 1000)) <= 300
    assert safe_error_summary(None) is None


# --- attempt counting and source state ---------------------------------------


def test_consecutive_failures_count_up_and_reset_after_a_success(db_engine):
    base = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
    _record(db_engine, "failed", at=base, error="boom")
    _record(db_engine, "failed", at=base + timedelta(minutes=30), error="boom")
    assert [r["attempt"] for r in _runs(db_engine)] == [1, 2]

    _record(db_engine, "success", at=base + timedelta(hours=1), data_as_of="2026-11-03")
    _record(db_engine, "failed", at=base + timedelta(hours=2), error="boom")
    assert [r["attempt"] for r in _runs(db_engine)] == [1, 2, 1, 1]


def test_source_turns_red_after_n_consecutive_failures(db_engine):
    base = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
    _record(db_engine, "success", at=base, data_as_of="2026-11-02")
    with Session(db_engine) as db:
        assert job_status(db, JOB_MARKET_DATA, user_id=1)["state"] == "ok"

    for i in range(1, FAILURE_THRESHOLD):
        _record(db_engine, "failed", at=base + timedelta(minutes=30 * i), error="provider down")
        with Session(db_engine) as db:
            status = job_status(db, JOB_MARKET_DATA, user_id=1)
        assert status["state"] == "warning"
        assert status["consecutive_failures"] == i

    _record(db_engine, "failed", at=base + timedelta(hours=5), error="provider down")
    with Session(db_engine) as db:
        status = job_status(db, JOB_MARKET_DATA, user_id=1)
    assert status["state"] == "failing"
    assert status["consecutive_failures"] == FAILURE_THRESHOLD
    assert status["last_error"] == "provider down"
    # Last success and data-as-of survive the failures.
    assert status["last_success_at"].startswith("2026-11-03T10:00")
    assert status["data_as_of"] == "2026-11-02"


def test_source_status_is_only_as_current_as_its_stalest_scope(db_engine):
    _record(db_engine, "success", scope="exchange:US", at=datetime(2026, 11, 3, 22, 0, tzinfo=UTC), data_as_of="2026-11-03")
    _record(db_engine, "success", scope="exchange:SGX", at=datetime(2026, 11, 2, 11, 0, tzinfo=UTC), data_as_of="2026-11-02")
    with Session(db_engine) as db:
        status = job_status(db, JOB_MARKET_DATA, user_id=1, scopes=["exchange:US", "exchange:SGX"])
    assert status["data_as_of"] == "2026-11-02"
    assert status["last_success_at"].startswith("2026-11-02T11:00")
    assert {s["scope"] for s in status["scopes"]} == {"exchange:US", "exchange:SGX"}


def test_scopes_that_no_longer_exist_do_not_keep_a_source_red(db_engine):
    for i in range(FAILURE_THRESHOLD):
        _record(db_engine, "failed", job=JOB_CRYPTO, scope="wallet:deleted", at=datetime(2026, 11, 3, i, tzinfo=UTC))
    _record(db_engine, "success", job=JOB_CRYPTO, scope="wallet:live", at=datetime(2026, 11, 3, 9, tzinfo=UTC))
    with Session(db_engine) as db:
        assert job_status(db, JOB_CRYPTO, user_id=1)["state"] == "failing"
        assert job_status(db, JOB_CRYPTO, user_id=1, scopes=["wallet:live"])["state"] == "ok"
        assert job_status(db, JOB_CRYPTO, user_id=1, scopes=[])["state"] == "not_configured"
        assert job_status(db, JOB_IBKR_FLEX, user_id=1)["state"] == "never_run"


def test_other_users_runs_are_not_shown(db_engine):
    with Session(db_engine) as db:
        record_job_run(
            db,
            job=JOB_CRYPTO,
            scope="wallet:theirs",
            trigger="manual",
            status="failed",
            started_at=datetime.now(tz=UTC),
            user_id=2,
            error="nope",
        )
        assert job_status(db, JOB_CRYPTO, user_id=1)["state"] == "never_run"
        assert job_status(db, JOB_CRYPTO, user_id=2)["state"] == "warning"


# --- crypto ------------------------------------------------------------------


def _insert_wallet(db_engine, wallet_id: str, *, chain_type="evm", chain="ethereum", address="0xsynthetic") -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO crypto_wallets (id, user_id, chain_type, chain, address, label, status, created_at) "
                "VALUES (:id, 1, :chain_type, :chain, :address, 'Synthetic', 'active', :now)"
            ),
            {"id": wallet_id, "chain_type": chain_type, "chain": chain, "address": address, "now": datetime.now(tz=UTC)},
        )


def _native(symbol: str, value: float) -> NativeBalance:
    return NativeBalance(
        symbol=symbol,
        decimals=18,
        raw_amount="1000000000000000000",
        normalized_amount=1.0,
        price_usd=value,
        value_usd=value,
    )


def _snapshot_rows(db_engine, wallet_id: str):
    with db_engine.connect() as conn:
        snapshots = conn.execute(
            text("SELECT id, total_usd, source_versions FROM crypto_wallet_snapshots WHERE wallet_id = :w ORDER BY id"),
            {"w": wallet_id},
        ).mappings().all()
        items = conn.execute(
            text(
                "SELECT i.chain, i.value_usd FROM crypto_wallet_snapshot_items i "
                "JOIN crypto_wallet_snapshots s ON s.id = i.snapshot_id WHERE s.wallet_id = :w ORDER BY i.chain"
            ),
            {"w": wallet_id},
        ).fetchall()
    return snapshots, items


def test_partial_evm_refresh_carries_failed_chains_forward_and_stays_due(db_engine, monkeypatch):
    wallet_id = "wallet-partial-carry"
    _insert_wallet(db_engine, wallet_id)
    monkeypatch.setenv("CRYPTO_EVM_CHAINS", "ethereum,base")
    monkeypatch.setenv("CRYPTO_EVM_TOKEN_CHAINS", "ethereum,base")
    failing: set[str] = set()

    def fake_fetch(chain_type, chain, address):
        if chain in failing:
            raise RuntimeError(f"rpc https://rpc.example.com/v2/SECRETKEY123456789012 failed for {chain}")
        return _native("ETH", 100.0 if chain == "ethereum" else 50.0), [], "synthetic"

    monkeypatch.setattr("app.crypto.ingest.fetch_wallet_holdings", fake_fetch)

    with Session(db_engine) as db:
        assert refresh_wallet_snapshot_outcome(db, wallet_id, user_id=1, automatic=True) == "success"
        assert crypto_scheduler._wallet_refresh_due(db, wallet_id) is False

    failing.add("base")
    with Session(db_engine) as db:
        assert refresh_wallet_snapshot_outcome(db, wallet_id, user_id=1, automatic=True) == "partial"
        # Due again although it was just refreshed: the retry fires for the failed chain.
        assert crypto_scheduler._wallet_refresh_due(db, wallet_id) is True
        assert crypto_scheduler._wallet_refresh_due(db, wallet_id, datetime.now(tz=UTC) - timedelta(hours=1)) is True

    slot = datetime.now(tz=UTC) - timedelta(hours=1)
    with Session(db_engine) as db:
        for _ in range(crypto_scheduler.PARTIAL_RETRY_ATTEMPTS - 1):
            assert refresh_wallet_snapshot_outcome(db, wallet_id, user_id=1, automatic=True) == "partial"
        # A chain down all day isn't re-fetched every retry: the slot is done after the cap.
        assert crypto_scheduler._wallet_refresh_due(db, wallet_id, slot) is False

    snapshots, items = _snapshot_rows(db_engine, wallet_id)
    assert len(snapshots) == 1
    assert float(snapshots[0]["total_usd"]) == 150.0  # base's 50 carried forward
    assert sorted((chain, float(value)) for chain, value in items) == [("base", 50.0), ("ethereum", 100.0)]
    versions = json.loads(snapshots[0]["source_versions"])
    assert versions["failed_chain_names"] == ["base"]
    assert "base" in versions["stale_chains"]
    assert "SECRETKEY" not in versions["failed_chains"]

    failing.clear()
    with Session(db_engine) as db:
        assert refresh_wallet_snapshot_outcome(db, wallet_id, user_id=1, automatic=False) == "success"
        assert crypto_scheduler._wallet_refresh_due(db, wallet_id) is False

    runs = _runs(db_engine, JOB_CRYPTO)
    assert [(r["status"], r["trigger"]) for r in runs] == [
        ("success", "scheduled"),
        *[("partial", "scheduled")] * crypto_scheduler.PARTIAL_RETRY_ATTEMPTS,
        ("success", "manual"),
    ]
    assert all(r["scope"] == f"wallet:{wallet_id}" for r in runs)
    assert "base" in runs[1]["error_summary"]


def test_crypto_run_where_every_wallet_failed_is_a_failure(db_engine, monkeypatch, caplog):
    for wallet_id in ("wallet-fail-a", "wallet-fail-b"):
        _insert_wallet(db_engine, wallet_id, address=f"0x{wallet_id}")
    monkeypatch.setenv("CRYPTO_EVM_CHAINS", "ethereum")
    monkeypatch.setenv("COINBASE_SCHEDULER_ENABLED", "0")
    monkeypatch.setattr(
        "app.crypto.ingest.fetch_wallet_holdings",
        lambda chain_type, chain, address: (_ for _ in ()).throw(RuntimeError("provider unavailable")),
    )

    with caplog.at_level(logging.INFO, logger="capitalos.crypto"):
        crypto_scheduler._refresh_wallets(only_stale=False)

    events = [r.getMessage() for r in caplog.records if r.name == "capitalos.crypto"]
    assert "crypto_refresh_failed" in events
    assert "crypto_refresh_succeeded" not in events
    runs = _runs(db_engine, JOB_CRYPTO)
    assert len(runs) == 2 and all(r["status"] == "failed" for r in runs)
    assert all(r["data_advanced"] in (0, False) for r in runs)


def test_crypto_refresh_hour_with_a_bad_value_falls_back_instead_of_raising(monkeypatch):
    monkeypatch.setenv("CRYPTO_REFRESH_HOUR_LOCAL", "midnight")
    assert crypto_scheduler._refresh_hour() == 0
    monkeypatch.setenv("CRYPTO_REFRESH_HOUR_LOCAL", "7")
    assert crypto_scheduler._refresh_hour() == 7
    monkeypatch.setenv("CRYPTO_REFRESH_HOUR_LOCAL", "99")
    assert crypto_scheduler._refresh_hour() == 0


# --- IBKR --------------------------------------------------------------------


def _seed_flex_accounts(db_engine, legacy_ids=(301, 302)) -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO broker_connections (id, user_id, platform_code, connection_type, status) "
                "VALUES (41, 1, 'IBKR', 'flex_api', 'active')"
            )
        )
        for i, legacy_id in enumerate(legacy_ids):
            conn.execute(
                text(
                    "INSERT INTO accounts (id, name, platform, account_type, currency, country) "
                    "VALUES (:id, :name, 'IBKR', 'BROKER', 'USD', 'US')"
                ),
                {"id": legacy_id, "name": f"Synthetic IBKR {i}"},
            )
            conn.execute(
                text(
                    "INSERT INTO broker_accounts (connection_id, legacy_account_id, broker_account_id, base_currency, status) "
                    "VALUES (41, :legacy, :code, 'USD', 'active')"
                ),
                {"legacy": legacy_id, "code": f"SYN{i}"},
            )


def _completed_import(db_engine, legacy_id: int, finished_at: datetime, report_date: date) -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO broker_import_runs (legacy_account_id, platform_code, source_type, status, finished_at, report_date_to) "
                "VALUES (:legacy, 'IBKR', :source_type, 'completed', :finished_at, :report_date)"
            ),
            {
                "legacy": legacy_id,
                "source_type": portfolio_scheduler.SOURCE_TYPE,
                "finished_at": finished_at,
                "report_date": report_date,
            },
        )


def test_expected_report_date_is_the_last_weekday_before_new_yorks_date():
    # 18:30 SGT on Wed 2026-11-04 is 05:30 Wed in New York: Tuesday's statement.
    assert portfolio_scheduler.expected_report_date(datetime(2026, 11, 4, 10, 30, tzinfo=UTC)) == date(2026, 11, 3)
    # Sunday and Monday (SGT) runs both expect Friday's statement.
    assert portfolio_scheduler.expected_report_date(datetime(2026, 11, 8, 10, 30, tzinfo=UTC)) == date(2026, 11, 6)
    assert portfolio_scheduler.expected_report_date(datetime(2026, 11, 9, 10, 30, tzinfo=UTC)) == date(2026, 11, 6)


def test_ibkr_due_check_is_per_account(db_engine):
    _seed_flex_accounts(db_engine)
    due = datetime(2026, 11, 4, 10, 30, tzinfo=UTC)
    # Account 301 imported today's statement; 302's import failed (no completed run).
    _completed_import(db_engine, 301, due + timedelta(minutes=5), date(2026, 11, 3))
    _completed_import(db_engine, 302, due - timedelta(days=1), date(2026, 11, 2))

    due_ids = [int(a["legacy_account_id"]) for a in portfolio_scheduler._due_accounts(due)]
    assert due_ids == [302]


def test_ibkr_old_statement_stays_due_until_the_stale_attempt_cap(db_engine):
    _seed_flex_accounts(db_engine, legacy_ids=(301,))
    due = datetime(2026, 11, 4, 10, 30, tzinfo=UTC)
    with Session(db_engine) as db:
        for i in range(portfolio_scheduler.STALE_STATEMENT_ATTEMPTS):
            assert portfolio_scheduler.account_import_due(db, 301, due) is True
            # Completed, but IBKR returned Monday's statement instead of Tuesday's.
            _completed_import(db_engine, 301, due + timedelta(minutes=30 * (i + 1)), date(2026, 11, 2))
        # A US holiday doesn't retry all day: the slot counts as done after the cap.
        assert portfolio_scheduler.account_import_due(db, 301, due) is False


def test_ibkr_import_records_success_no_new_data_and_scrubbed_failure(db_engine, monkeypatch):
    _seed_flex_accounts(db_engine, legacy_ids=(301,))
    due = datetime(2026, 11, 4, 10, 30, tzinfo=UTC)
    outcomes = iter(
        [
            {"report_date_to": "2026-11-03", "import_run_id": 1},
            {"report_date_to": "2026-11-03", "import_run_id": 2},
            {"report_date_to": "2026-11-02", "import_run_id": 3},
            RuntimeError("fetch https://flex.example.com/Send?t=TOKEN1234567890abcdef failed for U7654321"),
        ]
    )

    def fake_import(db, *, current_user_id, legacy_account_id, cutover_date=None):
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        _completed_import(db_engine, legacy_account_id, datetime.now(tz=UTC), date.fromisoformat(outcome["report_date_to"]))
        return outcome

    monkeypatch.setattr(portfolio_scheduler, "run_ibkr_flex_import_from_config", fake_import)
    with Session(db_engine) as db:
        for _ in range(3):
            portfolio_scheduler.run_import_and_record(db, current_user_id=1, legacy_account_id=301, trigger="scheduled", due=due)
        with pytest.raises(RuntimeError):
            portfolio_scheduler.run_import_and_record(db, current_user_id=1, legacy_account_id=301, trigger="manual", due=due)

    runs = _runs(db_engine, JOB_IBKR_FLEX)
    assert [r["status"] for r in runs] == ["success", "success", "no_new_data", "failed"]
    assert [bool(r["data_advanced"]) for r in runs] == [True, False, False, False]
    assert runs[0]["data_as_of"] == "2026-11-03"
    assert runs[3]["trigger"] == "manual"
    assert runs[3]["user_id"] == 1
    assert all(r["scope"] == "account:301" for r in runs)
    error = runs[3]["error_summary"]
    assert error.startswith("RuntimeError")
    assert "TOKEN" not in error and "U7654321" not in error and "flex.example.com" not in error


def test_ibkr_due_check_retries_only_after_the_gap_when_data_did_not_advance(monkeypatch):
    from app.core import catchup

    now = datetime(2026, 11, 4, 11, 0, tzinfo=UTC)
    monkeypatch.setattr(portfolio_scheduler, "_retry_gate", catchup.RetryGate())
    monkeypatch.setattr(portfolio_scheduler, "_due_accounts", lambda due: [{"user_id": 1, "legacy_account_id": 301}])
    calls = []
    monkeypatch.setattr(portfolio_scheduler, "_run_daily_imports", lambda accounts, due: calls.append(1) or True)

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz is None else now.astimezone(tz)

    monkeypatch.setattr(portfolio_scheduler, "datetime", FrozenDatetime)
    portfolio_scheduler._run_if_due()
    portfolio_scheduler._run_if_due()
    # The import "succeeded" but the account is still due (old statement): one
    # attempt, then the retry gap, not one per check.
    assert calls == [1]


# --- market data -------------------------------------------------------------


def test_exchange_refresh_with_no_quotes_is_a_failure():
    assert market_scheduler.exchange_run_status({"status": "partial", "requested_symbols": 5, "upserted_rows": 0}) == "failed"
    assert market_scheduler.exchange_run_status({"status": "partial", "requested_symbols": 5, "upserted_rows": 4}) == "partial"
    assert market_scheduler.exchange_run_status({"status": "success", "requested_symbols": 0, "upserted_rows": 0}) == "success"


def test_window_stays_due_when_the_latest_run_got_no_quotes(db_engine, monkeypatch):
    due = datetime(2026, 11, 4, 10, 45, tzinfo=UTC)
    monkeypatch.setattr(market_scheduler, "_latest_success_for_exchanges", lambda exchanges: due + timedelta(minutes=5))
    with Session(db_engine) as db:
        market_scheduler.record_exchange_runs(
            db,
            [{"exchange_code": "SGX", "status": "success", "requested_symbols": 3, "upserted_rows": 3, "trade_date": "2026-11-04"}],
            trigger="scheduled",
            started_at=due + timedelta(minutes=1),
        )
    assert market_scheduler._window_due(["SGX"], due) is False

    with Session(db_engine) as db:
        market_scheduler.record_exchange_runs(
            db,
            [{"exchange_code": "SGX", "status": "partial", "requested_symbols": 3, "upserted_rows": 0, "missing_symbols": 3}],
            trigger="manual",
            started_at=due + timedelta(minutes=10),
        )
    assert market_scheduler._window_due(["SGX"], due) is True
    runs = _runs(db_engine, JOB_MARKET_DATA)
    assert [(r["scope"], r["status"]) for r in runs] == [("exchange:SGX", "success"), ("exchange:SGX", "failed")]

    # A provider outage stops retrying after the cap for this slot (quota).
    for i in range(market_scheduler.FAILED_WINDOW_ATTEMPTS - 1):
        assert market_scheduler._window_due(["SGX"], due) is True
        with Session(db_engine) as db:
            market_scheduler.record_exchange_runs(
                db,
                [{"exchange_code": "SGX", "status": "partial", "requested_symbols": 3, "upserted_rows": 0}],
                trigger="scheduled",
                started_at=due + timedelta(minutes=40 + 30 * i),
            )
    assert market_scheduler._window_due(["SGX"], due) is False


# --- Data Hub ----------------------------------------------------------------


def test_data_hub_shows_job_status_per_source(client, seed_dashboard_data, db_engine, monkeypatch):
    monkeypatch.setenv("STOCK_EXCHANGES", "US")
    _seed_flex_accounts(db_engine, legacy_ids=(301,))
    base = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
    _record(db_engine, "success", job=JOB_IBKR_FLEX, scope="account:301", at=base, data_as_of="2026-11-02")
    for i in range(FAILURE_THRESHOLD):
        _record(
            db_engine,
            "failed",
            job=JOB_IBKR_FLEX,
            scope="account:301",
            at=base + timedelta(days=1, minutes=30 * i),
            error="IbkrFlexError: statement not ready",
        )
    _record(db_engine, "success", job=JOB_MARKET_DATA, scope="exchange:US", at=base, data_as_of="2026-11-03")

    resp = client.get("/dashboard/data-hub-summary")
    assert resp.status_code == 200
    statuses = {item["job"]: item for item in resp.json()["job_status"]}
    ibkr = statuses[JOB_IBKR_FLEX]
    assert ibkr["state"] == "failing"
    assert ibkr["consecutive_failures"] == FAILURE_THRESHOLD
    assert ibkr["failure_threshold"] == FAILURE_THRESHOLD
    assert ibkr["data_as_of"] == "2026-11-02"
    assert ibkr["last_error"] == "IbkrFlexError: statement not ready"
    assert ibkr["scopes"][0]["label"] == "Synthetic IBKR 0"
    assert statuses[JOB_MARKET_DATA]["state"] == "ok"
    assert statuses[JOB_MARKET_DATA]["data_as_of"] == "2026-11-03"
    assert statuses["fx_fill"]["state"] == "never_run"
    # Existing fields are still there (contract: add only).
    assert {"linked_accounts", "import_health", "market_data", "recent_activity"} <= set(resp.json())
