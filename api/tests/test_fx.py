"""FX rate table (#139): stored rates, bounded lookback, missing never 1.0,
provider outages, and the FX-date rule (balances at the anchor, flows at their
own date). Providers are always fakes; FX_DISABLE_REMOTE=1 blocks real HTTP."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import text

from app import fx
from app.market_data import scheduler as market_scheduler
from tests.canonical_test_helpers import seed_canonical_account_balance_for_test
from tests.fx_test_helpers import SYNTHETIC_FX_PER_EUR, USD_SGD, synthetic_fx
from tests.test_dividends import _seed_dividend_data

DAY = datetime(2026, 3, 2, tzinfo=timezone.utc)
# Captured at import (collection), before conftest swaps in the synthetic fake.
REAL_FETCH_FRANKFURTER = fx._fetch_frankfurter


def _store(db_engine, day: date, rates_per_eur: dict[str, float], source: str = "frankfurter", base: str = "EUR") -> None:
    with db_engine.begin() as conn:
        for quote, rate in rates_per_eur.items():
            conn.execute(
                text(
                    "INSERT INTO fx_rates (rate_date, base, quote, rate, source, fetched_at) "
                    "VALUES (:d, :b, :q, :r, :s, :f)"
                ),
                {"d": day.isoformat(), "b": base, "q": quote, "r": rate, "s": source, "f": "2026-01-01T00:00:00+00:00"},
            )


@pytest.fixture()
def provider_calls(monkeypatch):
    """Counts provider calls; the synthetic answer is kept unless a test swaps it."""
    calls: list[tuple] = []
    original = fx._fetch_frankfurter

    def counting(start, end):
        calls.append(("frankfurter", start, end))
        return original(start, end)

    monkeypatch.setattr(fx, "_fetch_frankfurter", counting)
    return calls


@pytest.fixture()
def providers_down(monkeypatch):
    calls: list[str] = []

    def down(*_args, **_kwargs):
        calls.append("call")
        raise httpx.ConnectError("provider down")

    monkeypatch.setattr(fx, "_fetch_frankfurter", down)
    monkeypatch.setattr(fx, "_fetch_erapi", down)
    return calls


# ─── Reading and filling the table ───────────────────────────────────────────


def test_rates_are_fetched_once_stored_and_then_read_locally(db_engine, provider_calls):
    rates = fx.get_rates(DAY, "SGD", {"USD", "HKD"})
    assert rates["SGD"] == 1.0
    assert rates["USD"] == pytest.approx(USD_SGD)
    assert rates["HKD"] == pytest.approx(synthetic_fx("HKD"))
    assert rates.quotes["USD"].source == "frankfurter"
    assert rates.complete
    assert len(provider_calls) == 1

    with db_engine.connect() as conn:
        stored = conn.execute(text("SELECT COUNT(*) FROM fx_rates WHERE base = 'EUR'")).scalar_one()
    assert stored >= len(SYNTHETIC_FX_PER_EUR)

    # A new process (empty in-memory cache) reads the stored rows: no provider call.
    fx._CACHE.clear()
    again = fx.get_rates(DAY, "SGD", {"USD", "INR"})
    assert again["INR"] == pytest.approx(synthetic_fx("INR"))
    assert len(provider_calls) == 1


def test_one_provider_call_covers_every_currency_and_many_dates(provider_calls):
    first = fx.get_rates(DAY, "SGD", {"USD"})
    fx.get_rates(DAY, "SGD", {"USD", "HKD"})
    fx.get_rates(DAY, "SGD", {"INR", "HKD", "EUR"})
    assert first["USD"] == pytest.approx(USD_SGD)
    assert len(provider_calls) == 1

    many = fx.get_rates_by_date([date(2025, 1, 15), date(2025, 6, 3), date(2025, 11, 20)], "SGD", {"USD"})
    assert all(r["USD"] == pytest.approx(USD_SGD) for r in many.values())
    assert len(provider_calls) == 2  # the whole range in one call


def test_base_to_base_is_one_without_any_rate(providers_down):
    rates = fx.get_rates(DAY, "SGD", {"SGD"})
    assert rates == {"SGD": 1.0}
    assert rates.complete
    assert providers_down == []


def test_unknown_currency_is_missing_never_one(provider_calls):
    rates = fx.get_rates(DAY, "SGD", {"USD", "XYZ"})
    assert "XYZ" not in rates
    assert rates.get("XYZ", 0.0) == 0.0
    assert rates.missing == {"XYZ"}
    assert rates["USD"] == pytest.approx(USD_SGD)


def test_latest_rate_within_lookback_is_used_and_not_stale(db_engine, providers_down):
    _store(db_engine, DAY.date() - timedelta(days=5), {"USD": 1.10, "SGD": 1.43})
    rates = fx.get_rates(DAY, "SGD", {"USD"})
    assert rates["USD"] == pytest.approx(1.43 / 1.10)
    quote = rates.quotes["USD"]
    assert quote.rate_date == DAY.date() - timedelta(days=5)
    assert quote.age_days == 5
    assert not quote.stale
    assert rates.complete


def test_rate_older_than_lookback_is_used_and_flagged_stale(db_engine, providers_down):
    _store(db_engine, DAY.date() - timedelta(days=30), {"USD": 1.10, "SGD": 1.43})
    rates = fx.get_rates(DAY, "SGD", {"USD"})
    assert rates["USD"] == pytest.approx(1.43 / 1.10)
    assert rates.stale == {"USD"}
    assert rates.quotes["USD"].age_days == 30
    assert not rates.missing


def test_rate_after_the_date_is_never_used(db_engine, providers_down):
    _store(db_engine, DAY.date() + timedelta(days=1), {"USD": 1.10, "SGD": 1.43})
    assert fx.get_rates(DAY, "SGD", {"USD"}).missing == {"USD"}


def test_lookback_is_configurable(db_engine, providers_down, monkeypatch):
    _store(db_engine, DAY.date() - timedelta(days=5), {"USD": 1.10, "SGD": 1.43})
    monkeypatch.setenv("FX_LOOKBACK_DAYS", "3")
    assert fx.get_rates(DAY, "SGD", {"USD"}).stale == {"USD"}


def test_provider_failure_is_negative_cached_and_never_raises(providers_down, monkeypatch):
    for _ in range(3):
        rates = fx.get_rates(DAY, "SGD", {"USD"})
        assert rates.missing == {"USD"}
    assert len(providers_down) == 1  # one try (a past date: no open.er-api), then remembered

    monkeypatch.setattr(fx, "_NEGATIVE_TTL_SECONDS", 0)
    fx._CACHE.pop(("rate", DAY.date(), "SGD", "USD"), None)
    fx.get_rates(DAY, "SGD", {"USD"})
    assert len(providers_down) == 2  # after the negative TTL it tries again


def test_ibkr_statement_rates_are_read(db_engine, providers_down):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO portfolio_fx_rates (import_run_id, report_date, from_currency, to_currency, rate, source_platform) "
                "VALUES (1, :d, 'USD', 'SGD', 1.34, 'IBKR')"
            ),
            {"d": (DAY.date() - timedelta(days=1)).isoformat()},
        )
    rates = fx.get_rates(DAY, "SGD", {"USD"})
    assert rates["USD"] == pytest.approx(1.34)
    assert rates.quotes["USD"].source == "ibkr"
    # The inverse direction works too: 1 SGD in USD.
    assert fx.get_rates(DAY, "USD", {"SGD"})["SGD"] == pytest.approx(1 / 1.34)


def test_erapi_is_only_used_for_today_and_stored_under_its_own_date(db_engine, monkeypatch):
    today = datetime.now(tz=timezone.utc).date()
    monkeypatch.setattr(fx, "_fetch_erapi", lambda: (today, {"SGD": 1.35, "TWD": 32.0}))

    assert fx.get_rates(datetime.now(tz=timezone.utc), "SGD", {"TWD"})["TWD"] == pytest.approx(1.35 / 32.0)
    # A past date never gets today's latest-only rate.
    assert fx.get_rates(DAY, "SGD", {"TWD"}).missing == {"TWD"}
    with db_engine.connect() as conn:
        rows = conn.execute(text("SELECT rate_date, base FROM fx_rates WHERE quote = 'TWD'")).fetchall()
    assert [(str(r[0])[:10], r[1]) for r in rows] == [(today.isoformat(), "USD")]


def test_env_fallback_is_the_last_resort(providers_down, monkeypatch):
    monkeypatch.setenv("FX_FALLBACK_RATES", '{"SGD":{"INR":70}}')
    rates = fx.get_rates(DAY, "SGD", {"INR"})
    assert rates["INR"] == pytest.approx(1 / 70.0)
    assert rates.quotes["INR"].source == "env"


def test_frankfurter_response_parsing_and_the_http_guard(monkeypatch):
    monkeypatch.setenv("FX_DISABLE_REMOTE", "0")
    seen = []

    class Resp:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def fake_get(url, params=None, **_kwargs):
        seen.append((url, params))
        if ".." in url:
            return Resp({"base": "EUR", "rates": {"2026-02-27": {"USD": 1.08}, "2026-03-02": {"USD": 1.09}}})
        return Resp({"base": "EUR", "date": "2026-02-27", "rates": {"USD": 1.08}})

    monkeypatch.setattr(fx.httpx, "get", fake_get)
    assert REAL_FETCH_FRANKFURTER(date(2026, 2, 25), date(2026, 3, 2)) == {
        date(2026, 2, 27): {"USD": 1.08},
        date(2026, 3, 2): {"USD": 1.09},
    }
    # A single (weekend) date: Frankfurter answers with the business day before.
    assert REAL_FETCH_FRANKFURTER(date(2026, 3, 1), date(2026, 3, 1)) == {date(2026, 2, 27): {"USD": 1.08}}
    assert seen[0] == ("https://api.frankfurter.app/2026-02-25..2026-03-02", {"from": "EUR"})

    monkeypatch.setenv("FX_DISABLE_REMOTE", "1")
    with pytest.raises(RuntimeError):
        REAL_FETCH_FRANKFURTER(date(2026, 3, 1), date(2026, 3, 1))
    assert len(seen) == 2  # FX_DISABLE_REMOTE=1 never reaches HTTP


def test_disable_remote_reads_only_the_store(db_engine, monkeypatch, provider_calls):
    monkeypatch.setattr(fx, "remote_enabled", lambda: False)
    _store(db_engine, DAY.date() - timedelta(days=2), {"USD": 1.10, "SGD": 1.43})
    assert fx.get_rates(DAY, "SGD", {"USD"})["USD"] == pytest.approx(1.43 / 1.10)
    assert fx.get_rates(DAY, "SGD", {"HKD"}).missing == {"HKD"}
    assert provider_calls == []


# ─── Daily fill (scheduler) ──────────────────────────────────────────────────


def test_daily_fill_runs_when_due_and_not_again(provider_calls):
    market_scheduler._fx_retry_gate.reset()
    market_scheduler._run_fx_fill_if_due()
    assert len(provider_calls) == 1
    assert fx.last_fill_at() is not None
    market_scheduler._run_fx_fill_if_due()
    assert len(provider_calls) == 1  # the fill already happened since the due time


def test_daily_fill_failure_waits_for_the_retry_gate(providers_down):
    market_scheduler._fx_retry_gate.reset()
    market_scheduler._run_fx_fill_if_due()
    attempts = len(providers_down)
    assert attempts >= 1
    market_scheduler._run_fx_fill_if_due()
    assert len(providers_down) == attempts  # retried only after SCHEDULER_RETRY_MINUTES
    market_scheduler._fx_retry_gate.reset()


# ─── Responses ───────────────────────────────────────────────────────────────


def _seed_xyz_cash(db_engine):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country) VALUES "
                "(7101, 'Home Bank', 'DBS', 'BANK', 'SGD', 'SG'), "
                "(7102, 'Exotic Bank', 'XBANK', 'BANK', 'XYZ', 'XX')"
            )
        )
    seed_canonical_account_balance_for_test(db_engine, account_id=7101, as_of="2026-02-06", currency="SGD", balance_base=1000)
    seed_canonical_account_balance_for_test(db_engine, account_id=7102, as_of="2026-02-06", currency="XYZ", balance_base=5000)


def test_unknown_currency_is_flagged_and_left_out_of_totals(client, db_engine):
    _seed_xyz_cash(db_engine)
    data = client.get("/dashboard/summary?month=2026-02&base_currency=SGD").json()
    assert data["net_worth"]["total"] == pytest.approx(1000.0)  # XYZ 5000 is not counted 1:1
    assert data["fx_incomplete"] is True
    assert data["fx_missing_currencies"] == ["XYZ"]

    boot = client.get("/dashboard/bootstrap?month=2026-02&base_currency=SGD").json()
    assert boot["fx_incomplete"] is True
    assert boot["fx_missing_currencies"] == ["XYZ"]


def test_provider_down_pages_load_from_stored_rates_and_flag_stale(client, db_engine, providers_down):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country) VALUES "
                "(7201, 'US Bank', 'CHASE', 'BANK', 'USD', 'US')"
            )
        )
    seed_canonical_account_balance_for_test(db_engine, account_id=7201, as_of="2026-02-06", currency="USD", balance_base=100)
    # Only an old stored rate: 40 days before the anchor (2026-03-01).
    _store(db_engine, date(2026, 1, 20), {"USD": 1.0, "SGD": 1.4})

    resp = client.get("/dashboard/summary?month=2026-02&base_currency=SGD")
    assert resp.status_code == 200
    data = resp.json()
    assert data["net_worth"]["cash"] == pytest.approx(140.0)
    assert data["fx_incomplete"] is False
    assert "USD" in data["fx_stale_currencies"]

    # With stored rates inside the lookback (for the anchor and for the live
    # "now" view), nothing is flagged.
    _store(db_engine, date(2026, 2, 27), {"USD": 1.0, "SGD": 1.3})
    _store(db_engine, datetime.now(tz=timezone.utc).date(), {"USD": 1.0, "SGD": 1.3})
    fx._CACHE.clear()
    from app.valuation_cache import clear_shared_cache

    clear_shared_cache()
    data = client.get("/dashboard/summary?month=2026-02&base_currency=SGD").json()
    assert data["net_worth"]["cash"] == pytest.approx(130.0)
    assert "USD" not in data["fx_stale_currencies"]


# ─── FX-date rule ────────────────────────────────────────────────────────────


def test_crypto_summary_converts_each_balance_at_its_anchor_date(client, db_engine, providers_down):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO crypto_wallets (id, chain_type, chain, address, status, created_at) "
                "VALUES ('w-fx', 'evm', 'ethereum', '0xfx', 'active', '2026-04-01T00:00:00+00:00')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO crypto_wallet_snapshots (id, wallet_id, as_of_date, fetched_at, total_usd) VALUES "
                "(9301, 'w-fx', '2026-05-01', '2026-05-01T00:00:00+00:00', 3000), "
                "(9302, 'w-fx', '2026-05-23', '2026-05-23T00:00:00+00:00', 3600)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO crypto_wallet_snapshot_items "
                "(snapshot_id, chain_type, chain, asset_kind, symbol, normalized_amount, price_usd, value_usd) VALUES "
                "(9301, 'evm', 'ethereum', 'native', 'ETH', 2, 1500, 3000), "
                "(9302, 'evm', 'ethereum', 'native', 'ETH', 2, 1800, 3600)"
            )
        )
    _store(db_engine, date(2026, 5, 1), {"USD": 1.0, "SGD": 1.3})  # April's boundary
    _store(db_engine, date(2026, 6, 1), {"USD": 1.0, "SGD": 1.4})  # May's boundary

    body = client.get("/crypto/summary?month=2026-05&base_currency=SGD").json()
    assert body["total_crypto_base"] == pytest.approx(3600 * 1.4)
    assert body["snapshot_total_base"] == pytest.approx(3000 * 1.3)
    assert body["snapshot_delta_base"] == pytest.approx(3600 * 1.4 - 3000 * 1.3)
    assert body["trend"][-1] == {"month": "2026-05", "value": pytest.approx(3600 * 1.4)}
    assert body["trend"][-2] == {"month": "2026-04", "value": pytest.approx(3000 * 1.3)}
    assert body["fx_incomplete"] is False, body["fx_missing_currencies"]


def test_dividends_convert_each_payment_at_its_own_date(client, db_engine, providers_down):
    _seed_dividend_data(db_engine)  # 100 USD on 2026-01-15 (-15 tax), 80 USD on 2026-02-15
    _store(db_engine, date(2026, 1, 15), {"USD": 1.0, "SGD": 1.3})
    _store(db_engine, date(2026, 2, 15), {"USD": 1.0, "SGD": 1.4})
    _store(db_engine, date(2026, 3, 1), {"USD": 1.0, "SGD": 1.5})  # end of range: not used for flows

    data = client.get(
        "/dividends/history?asset_id=901&from_month=2026-01&to_month=2026-02&base_currency=SGD"
    ).json()
    assert data["totals"]["gross"] == pytest.approx(100 * 1.3 + 80 * 1.4)
    assert data["totals"]["withholding"] == pytest.approx(15 * 1.3)
    assert [e["gross"] for e in data["events"]] == [pytest.approx(130.0), pytest.approx(112.0)]
    assert data["fx_incomplete"] is False

    summary = client.get("/dividends/summary?from_month=2026-01&to_month=2026-02&base_currency=SGD").json()
    assert summary["totals"]["gross"] == pytest.approx(242.0)
