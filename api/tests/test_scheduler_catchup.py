from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.core.catchup import RetryGate, most_recent_due, parse_hhmm, run_is_due

SGT = ZoneInfo("Asia/Singapore")
NY = ZoneInfo("America/New_York")


def test_most_recent_due_is_today_once_the_time_has_passed():
    now = datetime(2026, 11, 3, 11, 0, tzinfo=timezone.utc)  # 19:00 SGT
    assert most_recent_due(now, 18, 30, SGT) == datetime(2026, 11, 3, 10, 30, tzinfo=timezone.utc)


def test_most_recent_due_is_yesterday_before_the_time():
    now = datetime(2026, 11, 3, 0, 0, tzinfo=timezone.utc)  # 08:00 SGT
    assert most_recent_due(now, 18, 30, SGT) == datetime(2026, 11, 2, 10, 30, tzinfo=timezone.utc)


def test_most_recent_due_follows_new_york_dst():
    # 17:45 New York is 21:45 UTC under EDT (before 2026-11-01) and 22:45 UTC under EST.
    assert most_recent_due(datetime(2026, 10, 30, 23, 0, tzinfo=timezone.utc), 17, 45, NY) == datetime(
        2026, 10, 30, 21, 45, tzinfo=timezone.utc
    )
    assert most_recent_due(datetime(2026, 11, 2, 23, 0, tzinfo=timezone.utc), 17, 45, NY) == datetime(
        2026, 11, 2, 22, 45, tzinfo=timezone.utc
    )


def test_run_is_due():
    due = datetime(2026, 11, 2, 10, 30, tzinfo=timezone.utc)
    assert run_is_due(None, due) is True
    assert run_is_due(due - timedelta(seconds=1), due) is True
    assert run_is_due(due, due) is False
    assert run_is_due(due + timedelta(hours=1), due) is False


def test_parse_hhmm_falls_back_on_bad_values():
    assert parse_hhmm("07:05", (18, 30)) == (7, 5)
    assert parse_hhmm(None, (18, 30)) == (18, 30)
    assert parse_hhmm("25:00", (18, 30)) == (18, 30)
    assert parse_hhmm("oops", (18, 30)) == (18, 30)


def test_retry_gate(monkeypatch):
    monkeypatch.delenv("SCHEDULER_RETRY_MINUTES", raising=False)
    gate = RetryGate()
    now = datetime(2026, 11, 3, tzinfo=timezone.utc)
    assert gate.may_attempt(now)
    gate.record(now, succeeded=False)
    assert not gate.may_attempt(now + timedelta(minutes=29))
    assert gate.may_attempt(now + timedelta(minutes=30))
    gate.record(now, succeeded=True)
    assert gate.may_attempt(now)


def test_crypto_due_check_refreshes_once_after_missed_midnight(monkeypatch):
    import app.crypto.scheduler as crypto_scheduler

    calls = []
    state = {"due": True}

    def fake_refresh(**kwargs):
        calls.append(kwargs)
        state["due"] = False

    monkeypatch.setattr(crypto_scheduler, "_retry_gate", RetryGate())
    monkeypatch.setattr(crypto_scheduler, "_any_wallet_due", lambda due: state["due"])
    monkeypatch.setattr(crypto_scheduler, "_refresh_wallets", fake_refresh)

    crypto_scheduler._run_if_due()
    crypto_scheduler._run_if_due()

    assert len(calls) == 1
    assert calls[0]["only_stale"] is True
    assert calls[0]["due"] is not None
