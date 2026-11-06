"""The valuation clock (#143, #130 finding 1.10): one anchor rule, in the app
timezone, for the dashboard, History and its dirty marks."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app import wealth_rollup_dirty
from app.valuation import clock

# 06:00 SGT on 1 April 2026: still 31 March in UTC.
FIRST_SGT_MORNING = datetime(2026, 3, 31, 22, 0, tzinfo=timezone.utc)


@pytest.fixture()
def singapore(monkeypatch):
    monkeypatch.setenv("TZ", "Asia/Singapore")
    monkeypatch.setenv("SNAPSHOT_DAY", "1")


def _freeze(monkeypatch, instant: datetime) -> None:
    monkeypatch.setattr(clock, "_current_anchor_ts", lambda: instant.astimezone(clock.app_timezone()))


def test_now_and_today_are_in_the_app_timezone(singapore, monkeypatch):
    _freeze(monkeypatch, FIRST_SGT_MORNING)
    assert clock._current_anchor_ts().isoformat() == "2026-04-01T06:00:00+08:00"
    assert clock._app_today() == date(2026, 4, 1)


def test_last_month_is_completed_on_the_first_before_08_sgt(singapore, monkeypatch):
    """The month-end anchor (1 April) has passed once it is 1 April in the app
    timezone, whatever the UTC date."""
    _freeze(monkeypatch, FIRST_SGT_MORNING)
    march = clock._parse_month("2026-03")
    april = clock._parse_month("2026-04")
    assert clock._anchor_passed(clock._anchor_ts(march)) is True
    assert clock._completed_snapshot_month_start(march) == march
    assert clock._completed_snapshot_month_start(april) == march
    assert clock._latest_completed_month_start(clock._current_anchor_ts()) == march
    assert clock._effective_anchor_for_month(march) == (clock._anchor_ts(march), False)
    assert clock._effective_anchor_for_month(april)[1] is True


def test_dirty_marks_use_the_same_completion_rule(singapore):
    """A write dated 31 March must mark the March row (anchor 1 April), which
    History stores from 06:00 SGT on 1 April on."""
    assert wealth_rollup_dirty.latest_completed_anchor_date(FIRST_SGT_MORNING) == date(2026, 4, 1)
    assert wealth_rollup_dirty.latest_completed_anchor_date(datetime(2026, 3, 31, 15, 59, tzinfo=timezone.utc)) == date(
        2026, 3, 1
    )


def test_open_month_follows_the_app_timezone_west_of_utc(monkeypatch):
    """West of UTC the local month starts after 00:00 UTC; the open month is
    still the local one (it used to compare a UTC month start with a local
    instant, which made the current month look past there)."""
    monkeypatch.setenv("TZ", "America/New_York")
    monkeypatch.setenv("SNAPSHOT_DAY", "1")
    _freeze(monkeypatch, datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc))
    assert clock._effective_anchor_for_month(clock._parse_month("2026-04"))[1] is True
    assert clock._effective_anchor_for_month(clock._parse_month("2026-03"))[1] is False
    # 31 March 22:00 in New York is 1 April 02:00 UTC: March is still open there.
    _freeze(monkeypatch, datetime(2026, 4, 1, 2, 0, tzinfo=timezone.utc))
    assert clock._effective_anchor_for_month(clock._parse_month("2026-03"))[1] is True
    assert clock._anchor_passed(clock._anchor_ts(clock._parse_month("2026-03"))) is False


@pytest.mark.parametrize(
    ("snapshot_day", "now", "expected"),
    [
        # 23:00 UTC on 5 March is 07:00 SGT on 6 March: the 6 March anchor has passed.
        ("6", datetime(2026, 3, 5, 23, 0, tzinfo=timezone.utc), "2026-02"),
        ("6", datetime(2026, 3, 5, 15, 0, tzinfo=timezone.utc), "2026-01"),
    ],
)
def test_latest_completed_month_start_uses_the_local_date(singapore, monkeypatch, snapshot_day, now, expected):
    monkeypatch.setenv("SNAPSHOT_DAY", snapshot_day)
    assert clock._latest_completed_month_start(now).strftime("%Y-%m") == expected


@pytest.mark.parametrize(
    ("snapshot_day", "month", "expected"),
    [
        # SNAPSHOT_DAY=1 on 3 March: always the calendar month before.
        ("1", "2026-03", "2026-02"),
        ("1", "2026-02", "2026-01"),
        # SNAPSHOT_DAY=5 on 3 March: February's month-end (5 March) hasn't passed, so the live
        # month compares with January's, and February (shown at January's month-end) with December's.
        ("5", "2026-03", "2026-01"),
        ("5", "2026-02", "2025-12"),
        ("5", "2026-01", "2025-12"),
    ],
)
def test_month_view_compares_with_the_month_end_before_the_one_shown(singapore, monkeypatch, snapshot_day, month, expected):
    """#232: a month view's "vs last month" is the completed month-end before
    the figures it shows, the one Overview's headline compares with (D-24)."""
    monkeypatch.setenv("SNAPSHOT_DAY", snapshot_day)
    _freeze(monkeypatch, datetime(2026, 3, 3, 2, 0, tzinfo=timezone.utc))
    assert clock._month_view_compare_month_start(clock._parse_month(month)).strftime("%Y-%m") == expected


def test_trend_point_anchor_is_live_for_the_open_month_and_never_unpassed(singapore, monkeypatch):
    """#241 (D-61): a trend bar is the open month live, a completed month-end, or
    nothing, never an anchor that hasn't passed."""
    _freeze(monkeypatch, FIRST_SGT_MORNING)  # 1 April 06:00 SGT
    now = clock._current_anchor_ts()
    assert clock._trend_point_anchor(clock._parse_month("2026-04")) == (now, True)
    march_anchor, march_live = clock._trend_point_anchor(clock._parse_month("2026-03"))
    assert (march_anchor.date(), march_live) == (date(2026, 4, 1), False)
    assert clock._trend_point_anchor(clock._parse_month("2026-05")) == (None, False)


def test_trend_point_anchor_before_a_later_snapshot_day(singapore, monkeypatch):
    """SNAPSHOT_DAY=5 on 3 March: February's month-end (5 March) hasn't passed, so
    February has no bar; January's (5 February) has."""
    monkeypatch.setenv("SNAPSHOT_DAY", "5")
    _freeze(monkeypatch, datetime(2026, 3, 3, 2, 0, tzinfo=timezone.utc))
    assert clock._trend_point_anchor(clock._parse_month("2026-03"))[1] is True
    assert clock._trend_point_anchor(clock._parse_month("2026-02")) == (None, False)
    january_anchor, january_live = clock._trend_point_anchor(clock._parse_month("2026-01"))
    assert (january_anchor.date(), january_live) == (date(2026, 2, 5), False)
    for month in ("2025-10", "2025-11", "2025-12", "2026-01", "2026-02"):
        anchor, live = clock._trend_point_anchor(clock._parse_month(month))
        assert anchor is None or live or clock._anchor_passed(anchor), month
