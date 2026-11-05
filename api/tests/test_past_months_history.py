"""Past months don't change silently (#207, #130 findings 1.5 and 1.6).

- A card's liability is its dated statement balance (a ``credit_balance``
  snapshot per statement), read like a bank balance: a newer statement never
  changes an earlier month.
- An account closed on D contributes nothing at any anchor after D; earlier
  months are unchanged. Values carried forward from before a month are flagged.

All data is synthetic.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ingestion.card_balance_backfill import backfill_card_balances, summary_lines
from app.ingestion.card_balances import card_statement_balance, write_card_statement_balance
from app.valuation.clock import _anchor_ts
from app.valuation.facts import CARD_STATEMENT_MAX_AGE_DAYS, _credit_card_liability_details, _networth_components
from app.wealth_rollup_dirty import dirty_state
from tests.auth_helpers import signed_in_client
from tests.canonical_test_helpers import seed_canonical_account_balance_for_test
from tests.valuation_household import (
    DBS_CARD,
    DBS_SAVINGS,
    HSBC_USD,
    IBKR,
    MISFILED_CARD,
    SCENARIOS,
    SHAREKHAN,
    USER_A,
    build_household,
    household_env,
)

CARD = 9201
BANK = 9202
FEB = datetime(2026, 2, 1, tzinfo=timezone.utc)
MAR = datetime(2026, 3, 1, tzinfo=timezone.utc)
JAN = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _dbs_card_csv(path: Path, *, as_at: str, credit_limit: float, available: float, rows: list[tuple[str, str, float]]) -> Path:
    """A synthetic DBS card export: (date 'DD Mon YYYY', description, debit amount)."""
    lines = [
        "Card Transaction Details For:,DBS/POSB MasterCard Platinum 5555-5555-5555-1111,,,,,,",
        f"Transactions As At:,{as_at},,,,,,",
        ",,,,,,,",
        f"Credit Limit:,SGD {credit_limit:.2f},,,,,,",
        f"Available Limit:,SGD {available:.2f},,,,,,",
        ",,,,,,,",
        "Transaction Date,Transaction Posting Date,Transaction Description,Transaction Type,Payment Type,"
        "Transaction Status,Debit Amount,Credit Amount",
    ]
    for day, description, amount in rows:
        lines.append(f"{day},{day},{description},Retail Purchase,Contactless,Posted,{amount:.2f},")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


_FEB_ROWS = [("10 Feb 2026", "SYNTHETIC STORE A", 600.0), ("20 Feb 2026", "SYNTHETIC STORE B", 400.0)]
_MAR_ROWS = _FEB_ROWS + [("05 Mar 2026", "SYNTHETIC STORE C", 500.0), ("15 Mar 2026", "SYNTHETIC STORE D", 300.0)]


def _card_account(db_engine, account_id: int = CARD, *, user_id: int = 1) -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, user_id) VALUES "
                "(:id, 'Synthetic Card', 'DBS', 'CREDIT_CARD', 'SGD', 'SG', :u)"
            ),
            {"id": account_id, "u": user_id},
        )
        conn.execute(
            text(
                "INSERT INTO credit_card_accounts (account_id, card_name, issuer, credit_limit, statement_day, due_day) "
                "VALUES (:id, 'Synthetic Card', 'DBS', 10000, 28, 15)"
            ),
            {"id": account_id},
        )


def _upload(client: TestClient, account_id: int, path: Path) -> dict:
    with open(path, "rb") as f:
        resp = client.post(f"/ingest/upload?account_id={account_id}", files={"file": (path.name, f, "text/csv")})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "IMPORTED", body
    return body


def _liability(db_engine, anchor: datetime) -> float:
    db = Session(bind=db_engine)
    try:
        return _networth_components(db, anchor, "SGD", 1)["liabilities"]
    finally:
        db.close()


@pytest.fixture()
def sgd_only(monkeypatch):
    monkeypatch.setattr("app.valuation.fx.get_rates", lambda *_a, **_k: {"SGD": 1.0})
    os.makedirs(os.getenv("DATA_DIR", "/tmp/capitalos_test_data"), exist_ok=True)


# ─── Part A: card statement balances ─────────────────────────────────────────


def test_next_months_statement_leaves_last_months_card_liability_unchanged(client, db_engine, sgd_only, tmp_path):
    """Acceptance (#207): upload month M's statement, then M+1's: M is unchanged.

    February's statement (as at 26 Feb) says the card owes 1,500 (1,000 of
    February spend plus 500 carried from January). Before #207 a newer statement
    moved the single limits row past February's anchor, and February fell back to
    its transactions (1,000)."""
    _card_account(db_engine)
    feb_anchor, mar_anchor = _anchor_ts(FEB), _anchor_ts(MAR)

    _upload(client, CARD, _dbs_card_csv(tmp_path / "feb.csv", as_at="26 Feb 2026", credit_limit=10000, available=8500, rows=_FEB_ROWS))
    assert _liability(db_engine, feb_anchor) == pytest.approx(1500.0)

    _upload(client, CARD, _dbs_card_csv(tmp_path / "mar.csv", as_at="27 Mar 2026", credit_limit=10000, available=8700, rows=_MAR_ROWS))
    assert _liability(db_engine, feb_anchor) == pytest.approx(1500.0)  # unchanged
    assert _liability(db_engine, mar_anchor) == pytest.approx(1300.0)

    with db_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT as_of_date, balance_local, import_job_id FROM account_balance_snapshots "
                "WHERE account_id = :a AND balance_type = 'credit_balance' ORDER BY as_of_date"
            ),
            {"a": CARD},
        ).fetchall()
        assert [(str(r[0]), float(r[1])) for r in rows] == [("2026-02-26", -1500.0), ("2026-03-27", -1300.0)]
        assert all(r[2] is not None for r in rows)
        # The limits row (Spending page) still holds the newest statement.
        assert float(conn.execute(text("SELECT available_limit FROM credit_card_accounts WHERE account_id = :a"), {"a": CARD}).scalar()) == 8700.0


def test_a_statement_marks_history_from_its_own_date(client, db_engine, sgd_only, tmp_path):
    _card_account(db_engine)
    _upload(client, CARD, _dbs_card_csv(tmp_path / "mar.csv", as_at="27 Mar 2026", credit_limit=10000, available=8700, rows=_MAR_ROWS[2:]))
    db = Session(bind=db_engine)
    try:
        assert dirty_state(db, 1)[0] == date(2026, 3, 5)  # its earliest transaction
        db.execute(text("UPDATE wealth_rollup_dirty SET from_date = NULL"))
        db.commit()
    finally:
        db.close()
    # The same statement again: no new transactions, the balance rewritten on its date.
    _upload(client, CARD, _dbs_card_csv(tmp_path / "mar2.csv", as_at="27 Mar 2026", credit_limit=10000, available=8600, rows=_MAR_ROWS[2:]))
    db = Session(bind=db_engine)
    try:
        assert dirty_state(db, 1)[0] == date(2026, 3, 27)
    finally:
        db.close()


def test_removing_a_statement_upload_removes_its_balance(client, db_engine, sgd_only, tmp_path):
    _card_account(db_engine)
    _upload(client, CARD, _dbs_card_csv(tmp_path / "feb.csv", as_at="26 Feb 2026", credit_limit=10000, available=8500, rows=_FEB_ROWS))
    second = _upload(client, CARD, _dbs_card_csv(tmp_path / "mar.csv", as_at="27 Mar 2026", credit_limit=10000, available=8700, rows=_MAR_ROWS))
    resp = client.post(f"/ingest/jobs/{second['job_id']}/remove")
    assert resp.status_code == 200, resp.text
    # March's anchor reads February's statement again (within 45 days of 1 Apr).
    assert _liability(db_engine, _anchor_ts(MAR)) == pytest.approx(1500.0)


def test_each_card_parser_states_what_it_can():
    dbs = card_statement_balance(
        "dbs_credit_card_csv_v1",
        {"credit_limit": 10000.0, "available_limit": 9739.44, "transactions_as_at": "2026-07-04T00:00:00+00:00"},
    )
    assert dbs is not None and dbs.as_of_date == date(2026, 7, 4) and dbs.balance == pytest.approx(-260.56)
    uob = card_statement_balance(
        "uob_credit_card_xls_v1", {"statement_date": "2026-02-12T00:00:00+00:00", "statement_balance": 321.84}
    )
    assert uob is not None and uob.as_of_date == date(2026, 2, 12) and uob.balance == pytest.approx(-321.84)
    # Citi exports carry no balance; a DBS export without limits or a UOB file without a date state none.
    assert card_statement_balance("citi_credit_card_csv_v1", {}) is None
    assert card_statement_balance("dbs_credit_card_csv_v1", {"credit_limit": 1.0, "transactions_as_at": "2026-07-04"}) is None
    assert card_statement_balance("uob_credit_card_xls_v1", {"statement_balance": 10.0}) is None


def test_uob_statement_balance_is_the_liability_from_its_date(db_engine, sgd_only):
    _card_account(db_engine)
    db = Session(bind=db_engine)
    try:
        written = write_card_statement_balance(
            db,
            account_id=CARD,
            import_job_id=None,
            parser_key="uob_credit_card_xls_v1",
            parser_meta={"statement_date": "2026-02-12T00:00:00+00:00", "statement_balance": 321.84, "currency": "SGD"},
        )
        db.commit()
        assert written is not None
        assert dirty_state(db, 1)[0] == date(2026, 2, 12)
    finally:
        db.close()
    assert _liability(db_engine, _anchor_ts(JAN)) == pytest.approx(0.0)  # 1 Feb: before the statement
    assert _liability(db_engine, _anchor_ts(FEB)) == pytest.approx(321.84)


def test_a_statement_too_old_is_not_carried_forward(db_engine, sgd_only):
    """A statement balance counts up to CARD_STATEMENT_MAX_AGE_DAYS after its
    date; after that the card's transactions in the month are its liability."""
    assert CARD_STATEMENT_MAX_AGE_DAYS == 45
    _card_account(db_engine)
    seed_canonical_account_balance_for_test(
        db_engine, account_id=CARD, as_of="2026-01-20", currency="SGD", balance_base=-700.0, balance_type="credit_balance"
    )
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO transactions (ts, account_id, type, amount, currency) VALUES "
                "('2026-03-10 00:00:00+00:00', :a, 'EXPENSE', -250, 'SGD')"
            ),
            {"a": CARD},
        )
    db = Session(bind=db_engine)
    try:
        feb = _credit_card_liability_details(db, _anchor_ts(FEB), "SGD", 1)  # 1 Mar: 40 days later
        mar = _credit_card_liability_details(db, _anchor_ts(MAR), "SGD", 1)  # 1 Apr: 71 days later
    finally:
        db.close()
    assert feb == [{"account_id": CARD, "method": "statement", "as_of_date": date(2026, 1, 20), "value": pytest.approx(700.0)}]
    assert mar == [{"account_id": CARD, "method": "transactions", "as_of_date": None, "value": pytest.approx(250.0)}]


def test_an_overpaid_card_owes_nothing(db_engine, sgd_only):
    _card_account(db_engine)
    seed_canonical_account_balance_for_test(
        db_engine, account_id=CARD, as_of="2026-02-20", currency="SGD", balance_base=35.0, balance_type="credit_balance"
    )
    assert _liability(db_engine, _anchor_ts(FEB)) == 0.0


def test_a_card_statement_is_never_cash_or_cash_coverage(client, db_engine, sgd_only, tmp_path):
    _card_account(db_engine)
    _upload(client, CARD, _dbs_card_csv(tmp_path / "feb.csv", as_at="26 Feb 2026", credit_limit=10000, available=8500, rows=_FEB_ROWS))
    db = Session(bind=db_engine)
    try:
        components = _networth_components(db, _anchor_ts(FEB), "SGD", 1)
    finally:
        db.close()
    assert components["cash"] == 0.0
    summary = client.get("/dashboard/summary?month=2026-02&base_currency=SGD").json()
    assert summary["net_worth_snapshot_as_of"] is None  # a card statement isn't cash coverage


# ─── Backfill from stored statements ─────────────────────────────────────────


def _import_job(conn, job_id: int, account_id: int, parser_key: str, path: Path | str, status: str = "IMPORTED") -> None:
    conn.execute(
        text(
            "INSERT INTO import_jobs (id, account_id, platform, original_filename, stored_path, file_sha256, parser_key, status) "
            "VALUES (:id, :a, 'DBS', 'statement.csv', :p, 'synthetic', :k, :s)"
        ),
        {"id": job_id, "a": account_id, "p": str(path), "k": parser_key, "s": status},
    )


def test_backfill_writes_each_stored_statement_once(db_engine, tmp_path):
    _card_account(db_engine)
    feb = _dbs_card_csv(tmp_path / "feb.csv", as_at="26 Feb 2026", credit_limit=10000, available=8500, rows=_FEB_ROWS)
    mar = _dbs_card_csv(tmp_path / "mar.csv", as_at="27 Mar 2026", credit_limit=10000, available=8700, rows=_MAR_ROWS)
    mar_again = _dbs_card_csv(tmp_path / "mar2.csv", as_at="27 Mar 2026", credit_limit=10000, available=8650, rows=_MAR_ROWS)
    with db_engine.begin() as conn:
        _import_job(conn, 501, CARD, "dbs_credit_card_csv_v1", feb)
        _import_job(conn, 502, CARD, "dbs_credit_card_csv_v1", mar)
        _import_job(conn, 503, CARD, "dbs_credit_card_csv_v1", mar_again)  # the newer import for that date wins
        _import_job(conn, 504, CARD, "dbs_credit_card_csv_v1", tmp_path / "gone.csv")
        _import_job(conn, 505, CARD, "dbs_credit_card_csv_v1", feb, status="REMOVED")
        _import_job(conn, 506, CARD, "citi_credit_card_csv_v1", feb)
    # What migration 078 wrote from the card's current limits (no import recorded).
    seed_canonical_account_balance_for_test(
        db_engine, account_id=CARD, as_of="2026-03-27", currency="SGD", balance_base=-1350.0,
        balance_type="credit_balance", source_kind="backfill",
    )

    def snapshots() -> list[tuple[str, float, int | None]]:
        with db_engine.connect() as conn:
            return [
                (str(r[0]), float(r[1]), r[2])
                for r in conn.execute(
                    text(
                        "SELECT as_of_date, balance_local, import_job_id FROM account_balance_snapshots "
                        "WHERE account_id = :a AND balance_type = 'credit_balance' ORDER BY as_of_date"
                    ),
                    {"a": CARD},
                )
            ]

    before = snapshots()
    db = Session(bind=db_engine)
    try:
        dry = backfill_card_balances(db, apply=False)
        assert {j.job_id: j.action for j in dry.jobs} == {
            501: "insert", 502: "superseded", 503: "link", 504: "missing_file",
        }
        assert snapshots() == before  # a dry run writes nothing
        assert dirty_state(db, 1)[0] is None
        assert not any("1350" in line or "1500" in line for line in summary_lines(dry))  # never amounts

        applied = backfill_card_balances(db, apply=True)
        assert {j.job_id: j.action for j in applied.jobs} == {j.job_id: j.action for j in dry.jobs}
        assert snapshots() == [("2026-02-26", -1500.0, 501), ("2026-03-27", -1350.0, 503)]
        assert dirty_state(db, 1)[0] == date(2026, 2, 26)

        again = backfill_card_balances(db, apply=True)
        assert {j.job_id: j.action for j in again.jobs} == {
            501: "unchanged", 502: "superseded", 503: "unchanged", 504: "missing_file",
        }
        assert again.dirty_from == {}
        assert snapshots() == [("2026-02-26", -1500.0, 501), ("2026-03-27", -1350.0, 503)]
    finally:
        db.close()


# ─── Part B: closed accounts ─────────────────────────────────────────────────


@pytest.fixture()
def household(client: TestClient, db_engine, monkeypatch):
    """The synthetic household at the "mid" instant (2026-03-18 10:00 SGT)."""
    household_env(monkeypatch, SCENARIOS["mid"])
    build_household(db_engine, now=SCENARIOS["mid"])
    return client


def _net_worth(client: TestClient, month: str) -> dict:
    resp = client.get(f"/dashboard/summary?month={month}&base_currency=SGD")
    assert resp.status_code == 200, resp.text
    return resp.json()["net_worth"]


def _timeline_points(client: TestClient, *, backfill: bool = False) -> dict[str, dict]:
    if backfill:
        assert client.post("/dashboard/net-worth-timeline/backfill?months=6&base_currency=SGD").status_code == 200
    data = client.get("/dashboard/net-worth-timeline?months=6&base_currency=SGD").json()
    return {p["month"]: p for p in data["points"]}


_USER_A_ACCOUNTS = (DBS_SAVINGS, HSBC_USD, IBKR, SHAREKHAN, DBS_CARD, MISFILED_CARD)
_COMPONENTS = ("cash", "stocks_funds", "crypto", "liabilities", "total")


def test_closed_accounts_contribute_nothing_after_the_close_date(household, db_engine):
    """Acceptance (#207): closed on D, every component is 0 at anchors after D
    (cash, holdings, the IBKR NAV and cards); months on or before D are unchanged.
    History follows on its next read (D-29 marks)."""
    client = household
    jan_before, feb_before = _net_worth(client, "2026-01"), _net_worth(client, "2026-02")
    assert feb_before["cash"] > 0 and feb_before["stocks_funds"] > 0 and feb_before["liabilities"] > 0
    _timeline_points(client, backfill=True)  # History stored, nothing dirty

    for account_id in _USER_A_ACCOUNTS:
        resp = client.patch(f"/accounts/{account_id}", json={"closed_on": "2026-02-10"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["closed_on"] == "2026-02-10"

    db = Session(bind=db_engine)
    try:
        assert dirty_state(db, USER_A)[0] == date(2026, 2, 10)
    finally:
        db.close()
    jan_after, feb_after = _net_worth(client, "2026-01"), _net_worth(client, "2026-02")
    assert jan_after == jan_before  # anchor 1 Feb, before the close
    assert feb_after["cash"] == 0.0
    assert feb_after["stocks_funds"] == 0.0
    assert feb_after["liabilities"] == 0.0
    assert feb_after["crypto"] == pytest.approx(feb_before["crypto"])  # wallets aren't accounts
    assert feb_after["total"] == pytest.approx(feb_after["crypto"])

    points = _timeline_points(client)  # the next ordinary read
    for month, expected in (("2026-01", jan_after), ("2026-02", feb_after)):
        assert {k: points[month][k] for k in _COMPONENTS} == pytest.approx(expected, abs=0.01), month

    # Reopening restores February, in History too.
    for account_id in _USER_A_ACCOUNTS:
        resp = client.patch(f"/accounts/{account_id}", json={"closed_on": None})
        assert resp.status_code == 200, resp.text
        assert resp.json()["closed_on"] is None
    assert _net_worth(client, "2026-02") == pytest.approx(feb_before, abs=0.01)
    points = _timeline_points(client)
    assert {k: points["2026-02"][k] for k in _COMPONENTS} == pytest.approx(
        {k: feb_before[k] for k in _COMPONENTS}, abs=0.01
    )


def test_an_account_counts_on_its_close_date(household):
    """Closed on the anchor date itself (1 Mar, February's anchor): it still
    counts for February."""
    client = household
    feb_before = _net_worth(client, "2026-02")
    assert client.patch(f"/accounts/{DBS_SAVINGS}", json={"closed_on": "2026-03-01"}).status_code == 200
    assert _net_worth(client, "2026-02") == feb_before


def test_close_date_is_validated_and_owner_only(client, db_engine):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, user_id) VALUES "
                "(:a, 'Synthetic Bank', 'DBS', 'BANK', 'SGD', 'SG', 1)"
            ),
            {"a": BANK},
        )
    assert client.patch(f"/accounts/{BANK}", json={"closed_on": "2999-01-01"}).status_code == 400
    assert client.patch(f"/accounts/{BANK}", json={"closed_on": "not-a-date"}).status_code == 422
    assert client.patch(f"/accounts/{BANK}", json={}).status_code == 400
    assert client.patch("/accounts/999999", json={"closed_on": "2026-01-01"}).status_code == 404
    other = signed_in_client(db_engine, 2)
    assert other.patch(f"/accounts/{BANK}", json={"closed_on": "2026-01-01"}).status_code == 404
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT closed_on FROM accounts WHERE id = :a"), {"a": BANK}).scalar() is None


def test_accounts_list_flags_values_carried_forward(client, db_engine):
    """GET /accounts says, per account, the date of the newest fact a month
    reads and whether it predates the month (carried forward)."""
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, user_id) VALUES "
                "(:a, 'Synthetic Bank', 'DBS', 'BANK', 'SGD', 'SG', 1)"
            ),
            {"a": BANK},
        )
    seed_canonical_account_balance_for_test(db_engine, account_id=BANK, as_of="2025-12-20", currency="SGD", balance_base=900.0)

    def bank(month: str) -> dict:
        resp = client.get(f"/accounts?month={month}")
        assert resp.status_code == 200, resp.text
        return next(a for a in resp.json() if a["id"] == BANK)

    december = bank("2025-12")
    assert december["data_month"] == "2025-12"
    assert december["last_data_as_of"] == "2025-12-20"
    assert december["carried_forward_from"] is None
    february = bank("2026-02")
    assert february["last_data_as_of"] == "2025-12-20"
    assert february["carried_forward_from"] == "2025-12-20"

    assert client.patch(f"/accounts/{BANK}", json={"closed_on": "2026-01-15"}).status_code == 200
    february = bank("2026-02")
    assert february["closed_on"] == "2026-01-15"
    assert february["last_data_as_of"] is None and february["carried_forward_from"] is None
    # Default: the latest completed month.
    assert client.get("/accounts").json()[0]["data_month"] is not None
