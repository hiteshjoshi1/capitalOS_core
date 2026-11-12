"""#410 (UX U29): the Inbox's checks about the money itself."""
from datetime import date
from types import SimpleNamespace

from app.ingestion.upload_effect import effect, statement_day
from app.services.insight_alerts import recurring_item, unusual_move


def test_unusual_move_needs_both_a_big_multiple_and_a_real_share():
    steady = [(f"2026-{m:02d}", 100_000 + m * 1_000) for m in range(1, 11)]  # +1,000 a month
    assert unusual_move(steady, "SGD") is None
    jump = steady + [("2026-11", steady[-1][1] + 20_000)]  # 20x usual, 18% of the start
    item = unusual_move(jump, "SGD")
    assert item is not None and item.kind == "unusual_move" and item.id == "unusual_move:2026-11"
    assert "up S$ 20,000 in Nov 2026" in item.title and item.action.route == "/wealth/history"
    small = steady + [("2026-11", steady[-1][1] + 4_000)]  # 4x usual but under 5% of the start
    assert unusual_move(small, "SGD") is None


def test_unusual_move_wants_some_history():
    assert unusual_move([("2026-09", 100.0), ("2026-10", 200.0), ("2026-11", 900.0)], "SGD") is None


def _payment(months: int, amount: float, typical: float):
    return SimpleNamespace(account_id=7, merchant_counterparty="Netflix", months_present=months,
                           current_month_amount=amount, typical_amount=typical, cadence="monthly", card_name="UOB One")


def test_a_new_recurring_charge_and_one_above_its_usual():
    new = recurring_item(_payment(2, 23.0, 23.0), "SGD")
    assert new is not None and new.kind == "recurring_new" and "Netflix" in new.title
    up = recurring_item(_payment(6, 40.0, 23.0), "SGD")
    assert up is not None and up.kind == "recurring_up"
    assert recurring_item(_payment(6, 25.0, 23.0), "SGD") is None  # within its usual
    assert recurring_item(_payment(1, 2.0, 2.0), "SGD") is None  # too small to mention


def test_statement_day_is_the_newest_date_the_file_carries():
    txs = [{"ts": "2026-10-03T00:00:00"}, {"ts": "2026-10-28"}]
    assert statement_day(txs, [], {}, None) == date(2026, 10, 28)
    # Balances or holdings: the date they're written with (the file's date first).
    assert statement_day(txs, [{"symbol": "CASH"}], {"statement_date": "2026-11-01"}, None) == date(2026, 11, 1)
    assert statement_day([], [], {}, date(2026, 9, 30)) == date(2026, 9, 30)
    assert statement_day([], [], {}, None) is None


def test_effect_is_left_out_unless_both_sides_were_measured_for_one_month():
    before = {"month": "2026-10", "live": False, "base_currency": "SGD", "net_worth": 100, "balance": None, "balance_date": None}
    after = {**before, "net_worth": 150, "balance": 50, "balance_date": date(2026, 10, 31)}
    out = effect(before, after)
    assert out == {"month": "2026-10", "live": False, "base_currency": "SGD", "balance": 50.0, "balance_date": "2026-10-31",
                   "net_worth_before": 100.0, "net_worth_after": 150.0, "net_worth_change": 50.0}
    assert effect(None, after) is None and effect(before, {**after, "month": "2026-11"}) is None


def test_month_closed_counts_a_balance_carried_from_before_the_month(monkeypatch):
    from datetime import datetime

    from app.services import insight_alerts
    from app.valuation import clock, history

    monkeypatch.setattr(clock, "_current_anchor_ts", lambda: datetime(2026, 11, 12, 9, 0))
    monkeypatch.setattr(history, "_wealth_rollup_row", lambda *_a, **_k: {"source_freshness": [
        {"platform": "UOB", "as_of": "2026-07-04", "status": "carried"},
        {"platform": "DBS", "as_of": "2026-10-02", "status": "carried"},  # within October: fine
        {"platform": "IBKR", "as_of": "2026-10-30", "status": "fresh"},
    ]})
    items = insight_alerts.month_closed_items(None, SimpleNamespace(id=1), "SGD")
    assert [i.kind for i in items] == ["month_closed_stale"]
    assert items[0].title == "Oct 2026 closed with stale data" and "UOB (4 Jul)" in items[0].detail
    assert "DBS" not in items[0].detail
