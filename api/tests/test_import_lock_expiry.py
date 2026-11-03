"""#135: import/refresh locks left behind by a killed process must not wedge later runs."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

import app.main as main_module
import app.routers.portfolio as portfolio_router
from app.crypto.ingest import acquire_refresh_lock, refresh_lock_stale_after, release_refresh_lock
from app.portfolio.ibkr_flex import (
    IbkrFlexImportInProgress,
    _release_lock,
    _try_acquire_lock,
    import_lock_stale_after,
    run_ibkr_flex_import_from_xml,
)
from tests.test_ibkr_flex_phase1 import _seed_ibkr_account, _valid_flex_xml


def _seed_broker_account(db_engine, broker_account_id: int = 900) -> int:
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO broker_accounts (id, connection_id, broker_account_id, base_currency) "
                "VALUES (:id, 1, 'U-SYNTH-LOCK', 'USD')"
            ),
            {"id": broker_account_id},
        )
    return broker_account_id


def _insert_lock(db_engine, broker_account_id: int, *, owner: str, locked_at: datetime) -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO portfolio_import_locks (broker_account_id, source_type, lock_owner, locked_at) "
                "VALUES (:id, 'ibkr_flex_daily', :owner, :locked_at)"
            ),
            {"id": broker_account_id, "owner": owner, "locked_at": locked_at},
        )


def _lock_owner(db_engine, broker_account_id: int) -> str | None:
    with db_engine.connect() as conn:
        return conn.execute(
            text("SELECT lock_owner FROM portfolio_import_locks WHERE broker_account_id = :id"),
            {"id": broker_account_id},
        ).scalar()


def _now() -> datetime:
    return datetime.now(tz=timezone.utc).replace(microsecond=0)


# ── IBKR import lock ────────────────────────────────────────────────────────


def test_stale_threshold_defaults_to_30_minutes_and_reads_env(monkeypatch):
    monkeypatch.delenv("IBKR_IMPORT_LOCK_STALE_MINUTES", raising=False)
    assert import_lock_stale_after() == timedelta(minutes=30)
    monkeypatch.setenv("IBKR_IMPORT_LOCK_STALE_MINUTES", "5")
    assert import_lock_stale_after() == timedelta(minutes=5)
    for bad in ("nonsense", "0", "-3"):
        monkeypatch.setenv("IBKR_IMPORT_LOCK_STALE_MINUTES", bad)
        assert import_lock_stale_after() == timedelta(minutes=30)


def test_free_lock_is_acquired_and_released(db_engine):
    broker_account_id = _seed_broker_account(db_engine)
    db = sessionmaker(bind=db_engine)()
    try:
        owner = _try_acquire_lock(db, broker_account_id, "ibkr_flex_daily")
        db.commit()
        assert _lock_owner(db_engine, broker_account_id) == owner
        _release_lock(db, broker_account_id, owner)
        db.commit()
        assert _lock_owner(db_engine, broker_account_id) is None
    finally:
        db.close()


def test_fresh_lock_still_refuses_a_concurrent_import(db_engine, monkeypatch):
    monkeypatch.delenv("IBKR_IMPORT_LOCK_STALE_MINUTES", raising=False)
    broker_account_id = _seed_broker_account(db_engine)
    _insert_lock(db_engine, broker_account_id, owner="live-import", locked_at=_now() - timedelta(minutes=5))

    db = sessionmaker(bind=db_engine)()
    try:
        with pytest.raises(IbkrFlexImportInProgress):
            _try_acquire_lock(db, broker_account_id, "ibkr_flex_daily")
    finally:
        db.close()
    assert _lock_owner(db_engine, broker_account_id) == "live-import"


def test_stale_lock_is_taken_over_with_a_warning(db_engine, monkeypatch, caplog):
    monkeypatch.delenv("IBKR_IMPORT_LOCK_STALE_MINUTES", raising=False)
    broker_account_id = _seed_broker_account(db_engine)
    _insert_lock(db_engine, broker_account_id, owner="killed-import", locked_at=_now() - timedelta(minutes=31))

    db = sessionmaker(bind=db_engine)()
    try:
        with caplog.at_level(logging.WARNING, logger="capitalos.portfolio.ibkr_flex"):
            owner = _try_acquire_lock(db, broker_account_id, "ibkr_flex_daily")
        db.commit()
    finally:
        db.close()

    assert owner != "killed-import"
    assert _lock_owner(db_engine, broker_account_id) == owner
    assert any(r.getMessage() == "ibkr_flex_stale_import_lock_taken_over" for r in caplog.records)


def test_a_taken_over_lock_refuses_the_next_import(db_engine, monkeypatch):
    # The takeover refreshes locked_at, so a second caller sees a live lock.
    monkeypatch.delenv("IBKR_IMPORT_LOCK_STALE_MINUTES", raising=False)
    broker_account_id = _seed_broker_account(db_engine)
    _insert_lock(db_engine, broker_account_id, owner="killed-import", locked_at=_now() - timedelta(hours=3))

    Session = sessionmaker(bind=db_engine)
    first = Session()
    second = Session()
    try:
        _try_acquire_lock(first, broker_account_id, "ibkr_flex_daily")
        first.commit()
        with pytest.raises(IbkrFlexImportInProgress):
            _try_acquire_lock(second, broker_account_id, "ibkr_flex_daily")
    finally:
        first.close()
        second.close()


def test_threshold_is_configurable(db_engine, monkeypatch):
    monkeypatch.setenv("IBKR_IMPORT_LOCK_STALE_MINUTES", "2")
    broker_account_id = _seed_broker_account(db_engine)
    _insert_lock(db_engine, broker_account_id, owner="killed-import", locked_at=_now() - timedelta(minutes=5))

    db = sessionmaker(bind=db_engine)()
    try:
        owner = _try_acquire_lock(db, broker_account_id, "ibkr_flex_daily")
        db.commit()
    finally:
        db.close()
    assert _lock_owner(db_engine, broker_account_id) == owner


def test_lock_row_with_sqlite_current_timestamp_format_is_understood(db_engine, monkeypatch):
    # Rows written by SQL defaults (naive 'YYYY-MM-DD HH:MM:SS', UTC) are parsed, not treated as stale.
    monkeypatch.delenv("IBKR_IMPORT_LOCK_STALE_MINUTES", raising=False)
    broker_account_id = _seed_broker_account(db_engine)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO portfolio_import_locks (broker_account_id, source_type, lock_owner, locked_at) "
                "VALUES (:id, 'ibkr_flex_daily', 'live-import', CURRENT_TIMESTAMP)"
            ),
            {"id": broker_account_id},
        )
    db = sessionmaker(bind=db_engine)()
    try:
        with pytest.raises(IbkrFlexImportInProgress):
            _try_acquire_lock(db, broker_account_id, "ibkr_flex_daily")
    finally:
        db.close()


def _route_import_through_xml(monkeypatch, db_engine, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    def fake_import_from_config(db, *, current_user_id, legacy_account_id, cutover_date=None):
        return run_ibkr_flex_import_from_xml(
            db,
            current_user_id=current_user_id,
            legacy_account_id=legacy_account_id,
            xml_text=_valid_flex_xml(),
            cutover_date=date(2026, 2, 1),
        )

    monkeypatch.setattr(portfolio_router, "run_ibkr_flex_import_from_config", fake_import_from_config)


def _broker_account_after_first_import(db_engine) -> int:
    with db_engine.connect() as conn:
        return int(conn.execute(text("SELECT id FROM broker_accounts LIMIT 1")).scalar())


def test_import_now_returns_409_while_a_fresh_lock_is_held(client, db_engine, tmp_path, monkeypatch):
    monkeypatch.delenv("IBKR_IMPORT_LOCK_STALE_MINUTES", raising=False)
    _seed_ibkr_account(db_engine)
    _route_import_through_xml(monkeypatch, db_engine, tmp_path)
    assert client.post("/portfolio/ibkr-flex/import-now", params={"account_id": 300}).status_code == 200

    broker_account_id = _broker_account_after_first_import(db_engine)
    _insert_lock(db_engine, broker_account_id, owner="live-import", locked_at=_now() - timedelta(minutes=1))

    response = client.post("/portfolio/ibkr-flex/import-now", params={"account_id": 300})
    assert response.status_code == 409, response.text
    assert _lock_owner(db_engine, broker_account_id) == "live-import"


def test_import_now_succeeds_over_a_stale_lock_and_releases_it(client, db_engine, tmp_path, monkeypatch):
    monkeypatch.delenv("IBKR_IMPORT_LOCK_STALE_MINUTES", raising=False)
    _seed_ibkr_account(db_engine)
    _route_import_through_xml(monkeypatch, db_engine, tmp_path)
    assert client.post("/portfolio/ibkr-flex/import-now", params={"account_id": 300}).status_code == 200

    broker_account_id = _broker_account_after_first_import(db_engine)
    # A process killed mid-import (reload, deploy) left this row behind.
    _insert_lock(db_engine, broker_account_id, owner="killed-import", locked_at=_now() - timedelta(hours=2))

    response = client.post("/portfolio/ibkr-flex/import-now", params={"account_id": 300})
    assert response.status_code == 200, response.text
    assert _lock_owner(db_engine, broker_account_id) is None


# ── Crypto refresh flag ─────────────────────────────────────────────────────


def _seed_wallet(db_engine, wallet_id: str, *, in_progress: bool, started_at: datetime | None) -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO crypto_wallets (id, chain_type, chain, address, label, status, created_at, "
                "refresh_in_progress, refresh_started_at) "
                "VALUES (:id, 'evm', 'ethereum', '0xSYNTHETICLOCK', 'Test', 'active', :now, :in_progress, :started_at)"
            ),
            {
                "id": wallet_id,
                "now": datetime.now(tz=timezone.utc),
                "in_progress": in_progress,
                "started_at": started_at,
            },
        )


def test_crypto_refresh_threshold_defaults_to_30_minutes(monkeypatch):
    monkeypatch.delenv("CRYPTO_REFRESH_LOCK_STALE_MINUTES", raising=False)
    assert refresh_lock_stale_after() == timedelta(minutes=30)
    monkeypatch.setenv("CRYPTO_REFRESH_LOCK_STALE_MINUTES", "10")
    assert refresh_lock_stale_after() == timedelta(minutes=10)


def test_crypto_free_flag_is_acquired_once(db_engine):
    _seed_wallet(db_engine, "wallet-free", in_progress=False, started_at=None)
    db = sessionmaker(bind=db_engine)()
    try:
        assert acquire_refresh_lock(db, "wallet-free") is True
        db.commit()
        assert acquire_refresh_lock(db, "wallet-free") is False
        release_refresh_lock(db, "wallet-free")
        db.commit()
        assert acquire_refresh_lock(db, "wallet-free") is True
    finally:
        db.close()


def test_crypto_fresh_flag_still_refuses(db_engine, monkeypatch):
    monkeypatch.delenv("CRYPTO_REFRESH_LOCK_STALE_MINUTES", raising=False)
    _seed_wallet(
        db_engine,
        "wallet-live",
        in_progress=True,
        started_at=datetime.now(tz=timezone.utc) - timedelta(minutes=5),
    )
    db = sessionmaker(bind=db_engine)()
    try:
        assert acquire_refresh_lock(db, "wallet-live") is False
    finally:
        db.close()


def test_crypto_stale_flag_is_taken_over_with_a_warning(db_engine, monkeypatch, caplog):
    monkeypatch.delenv("CRYPTO_REFRESH_LOCK_STALE_MINUTES", raising=False)
    _seed_wallet(
        db_engine,
        "wallet-stale",
        in_progress=True,
        started_at=datetime.now(tz=timezone.utc) - timedelta(minutes=45),
    )
    db = sessionmaker(bind=db_engine)()
    try:
        with caplog.at_level(logging.WARNING, logger="capitalos.crypto"):
            assert acquire_refresh_lock(db, "wallet-stale") is True
        db.commit()
        # The takeover restarted the clock, so a concurrent refresh is refused again.
        assert acquire_refresh_lock(db, "wallet-stale") is False
    finally:
        db.close()
    assert any(r.getMessage() == "crypto_stale_refresh_lock_taken_over" for r in caplog.records)


def test_crypto_flag_without_start_time_is_treated_as_stale(db_engine):
    _seed_wallet(db_engine, "wallet-nostart", in_progress=True, started_at=None)
    db = sessionmaker(bind=db_engine)()
    try:
        assert acquire_refresh_lock(db, "wallet-nostart") is True
    finally:
        db.close()


# ── Scheduler shutdown ──────────────────────────────────────────────────────


def test_lifespan_stops_all_three_schedulers_on_exit(monkeypatch):
    calls: list[str] = []
    for name in ("start_scheduler", "start_market_scheduler", "start_portfolio_scheduler"):
        monkeypatch.setattr(main_module, name, lambda name=name: calls.append(name))
    for name in ("stop_scheduler", "stop_market_scheduler", "stop_portfolio_scheduler"):
        monkeypatch.setattr(main_module, name, lambda name=name: calls.append(name))

    with TestClient(main_module.app):
        assert not any(c.startswith("stop_") for c in calls)

    assert sorted(c for c in calls if c.startswith("stop_")) == [
        "stop_market_scheduler",
        "stop_portfolio_scheduler",
        "stop_scheduler",
    ]


@pytest.mark.parametrize(
    "module_path",
    ["app.crypto.scheduler", "app.market_data.scheduler", "app.portfolio.scheduler"],
)
def test_stop_scheduler_shuts_down_without_waiting(monkeypatch, module_path):
    import importlib

    module = importlib.import_module(module_path)

    class DummyScheduler:
        def __init__(self):
            self.shutdown_calls: list[bool] = []

        def shutdown(self, wait=True):
            self.shutdown_calls.append(wait)

    dummy = DummyScheduler()
    monkeypatch.setattr(module, "_scheduler", dummy)

    module.stop_scheduler()
    module.stop_scheduler()  # idempotent: nothing left to stop

    assert dummy.shutdown_calls == [False]
    assert module._scheduler is None


def test_stop_scheduler_swallows_shutdown_errors(monkeypatch):
    import app.crypto.scheduler as crypto_scheduler

    class BrokenScheduler:
        def shutdown(self, wait=True):
            raise RuntimeError("already stopped")

    monkeypatch.setattr(crypto_scheduler, "_scheduler", BrokenScheduler())
    crypto_scheduler.stop_scheduler()
    assert crypto_scheduler._scheduler is None
