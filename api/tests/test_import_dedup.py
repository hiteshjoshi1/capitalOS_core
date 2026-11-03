"""#157: imports dedup by occurrence count (uploads, id-less IBKR lines) and by
broker id (IBKR lines and trades that carry one), never by a value tuple that
drops a genuine repeat or doubles an edited line."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.ingestion.parsers.ocbc_account_csv_v1 import parse_ocbc_account_csv
from app.ingestion.runner import _source_fingerprint
from tests.test_ibkr_dividends_ledger import _flex_xml, _import
from tests.test_ibkr_flex_phase1 import _seed_ibkr_account

ACCOUNT_ID = 951

_HEADER = (
    "Account details for:,360 Account 000-000000-009\n"
    "Available Balance,1000.00\n"
    "Ledger Balance,1000.00\n"
    "Transaction date,Value date,Description,Withdrawals(SGD),Deposits(SGD)\n"
)
ROW_A = "08/03/2026,08/03/2026,NETS TEST COFFEE,4.50,\n"
ROW_B = "09/03/2026,09/03/2026,NETS TEST GROCER,32.10,\n"
ROW_C = "10/03/2026,10/03/2026,NETS TEST BAKERY,7.80,\n"


def _seed_bank_account(db_engine) -> None:
    db = sessionmaker(bind=db_engine)()
    try:
        db.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country) VALUES "
                "(:id, 'Test Bank', 'OCBC', 'BANK', 'SGD', 'SG')"
            ),
            {"id": ACCOUNT_ID},
        )
        db.commit()
    finally:
        db.close()


def _upload(client, tmp_path: Path, name: str, *rows: str) -> dict:
    path = tmp_path / name
    path.write_text(_HEADER + "".join(rows), encoding="utf-8")
    with open(path, "rb") as f:
        resp = client.post(
            f"/ingest/upload?account_id={ACCOUNT_ID}",
            files={"file": ("statement.csv", f, "text/csv")},
        )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["status"] == "IMPORTED", payload
    return payload["counts"]


def _stored(db_engine) -> list[tuple]:
    with db_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT merchant_counterparty, amount, source_fingerprint FROM transactions "
                "WHERE account_id = :account_id ORDER BY id"
            ),
            {"account_id": ACCOUNT_ID},
        ).fetchall()


def test_two_identical_same_day_purchases_are_both_stored(client, db_engine, tmp_path):
    _seed_bank_account(db_engine)
    counts = _upload(client, tmp_path, "one.csv", ROW_A, ROW_A)

    assert counts["transactions_inserted"] == 2
    assert counts["duplicates_skipped"] == 0
    rows = _stored(db_engine)
    assert [r[0] for r in rows] == ["NETS TEST COFFEE", "NETS TEST COFFEE"]
    # Each occurrence has its own identity.
    assert rows[0][2] and rows[1][2] and rows[0][2] != rows[1][2]


def test_reuploading_the_same_file_inserts_nothing(client, db_engine, tmp_path):
    _seed_bank_account(db_engine)
    _upload(client, tmp_path, "one.csv", ROW_A, ROW_A, ROW_B)
    counts = _upload(client, tmp_path, "two.csv", ROW_A, ROW_A, ROW_B)

    assert counts["transactions_inserted"] == 0
    assert counts["duplicates_skipped"] == 3
    assert len(_stored(db_engine)) == 3


def test_overlapping_file_inserts_only_the_new_row(client, db_engine, tmp_path):
    _seed_bank_account(db_engine)
    _upload(client, tmp_path, "one.csv", ROW_A, ROW_B)
    counts = _upload(client, tmp_path, "two.csv", ROW_A, ROW_B, ROW_C)

    assert counts["transactions_inserted"] == 1
    assert counts["duplicates_skipped"] == 2
    assert sorted(r[0] for r in _stored(db_engine)) == ["NETS TEST BAKERY", "NETS TEST COFFEE", "NETS TEST GROCER"]


def test_a_later_file_with_one_more_repeat_adds_only_that_repeat(client, db_engine, tmp_path):
    _seed_bank_account(db_engine)
    _upload(client, tmp_path, "one.csv", ROW_A)
    counts = _upload(client, tmp_path, "two.csv", ROW_A, ROW_A)

    assert counts["transactions_inserted"] == 1
    assert counts["duplicates_skipped"] == 1
    assert len(_stored(db_engine)) == 2


def test_a_reclassified_row_is_not_inserted_again(client, db_engine, tmp_path):
    _seed_bank_account(db_engine)
    _upload(client, tmp_path, "one.csv", ROW_A, ROW_B)
    with db_engine.begin() as conn:
        conn.execute(
            text("UPDATE transactions SET category = 'Food::Coffee' WHERE account_id = :account_id"),
            {"account_id": ACCOUNT_ID},
        )

    counts = _upload(client, tmp_path, "two.csv", ROW_A, ROW_B)

    assert counts["transactions_inserted"] == 0
    assert counts["duplicates_skipped"] == 2
    assert len(_stored(db_engine)) == 2


def test_rows_imported_before_the_fingerprint_column_still_count(client, db_engine, tmp_path):
    # A row stored before #157 has no source_fingerprint (and an older category);
    # it still counts as the first occurrence of its key.
    _seed_bank_account(db_engine)
    legacy_file = tmp_path / "legacy.csv"
    legacy_file.write_text(_HEADER + ROW_A, encoding="utf-8")
    legacy = parse_ocbc_account_csv(str(legacy_file)).transactions[0]
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO transactions (ts, account_id, amount, type, currency, category, merchant_counterparty, source, notes) "
                "VALUES (:ts, :account_id, :amount, :type, :currency, 'Old::Category', :merchant, 'OCBC', 'fp:legacy')"
            ),
            {
                "ts": legacy["ts"],
                "account_id": ACCOUNT_ID,
                "amount": legacy["amount"],
                "type": legacy["type"],
                "currency": legacy["currency"],
                "merchant": legacy["merchant_counterparty"],
            },
        )

    counts = _upload(client, tmp_path, "one.csv", ROW_A, ROW_A)

    assert counts["transactions_inserted"] == 1
    assert counts["duplicates_skipped"] == 1
    rows = _stored(db_engine)
    assert len(rows) == 2
    assert rows[0][2] is None and rows[1][2]


def test_a_taken_fingerprint_moves_to_the_next_free_occurrence(client, db_engine, tmp_path):
    # Two coffees stored, the first deleted by hand: the file's two coffees now
    # count one stored row, so one is inserted. Its natural index (2) is still held
    # by the surviving row, so it takes 3 instead of failing the unique index.
    _seed_bank_account(db_engine)
    _upload(client, tmp_path, "one.csv", ROW_A, ROW_A)
    with db_engine.begin() as conn:
        first_id = conn.execute(
            text("SELECT MIN(id) FROM transactions WHERE account_id = :account_id"), {"account_id": ACCOUNT_ID}
        ).scalar()
        conn.execute(text("DELETE FROM transactions WHERE id = :id"), {"id": first_id})

    counts = _upload(client, tmp_path, "two.csv", ROW_A, ROW_A)

    assert counts["transactions_inserted"] == 1
    fingerprints = [r[2] for r in _stored(db_engine)]
    assert len(fingerprints) == 2 and len(set(fingerprints)) == 2


def test_source_fingerprint_ignores_category_and_numeric_formatting():
    from datetime import datetime, timezone

    ts = datetime(2026, 3, 8, tzinfo=timezone.utc)
    base = {"ts": ts, "type": "EXPENSE", "amount": -4.5, "currency": "SGD", "merchant_counterparty": "X"}
    assert _source_fingerprint(1, base, 1) == _source_fingerprint(1, {**base, "category": "Other"}, 1)
    assert _source_fingerprint(1, base, 1) == _source_fingerprint(1, {**base, "amount": -4.50}, 1)
    assert _source_fingerprint(1, base, 1) != _source_fingerprint(1, base, 2)


# --- IBKR cash ledger and trades ---------------------------------------------

_DIVIDEND = (
    '<StatementOfFundsLine currency="SGD" assetCategory="STK" symbol="TST" description="TEST CORP" '
    'conid="1111" date="20261024" activityCode="DIV" activityDescription="{text}" amount="25.0" '
    'transactionID="9000001" />'
)


def _ledger_rows(db_engine, where: str) -> list[tuple]:
    with db_engine.connect() as conn:
        return conn.execute(
            text(f"SELECT broker_activity_id, description, amount FROM portfolio_cash_ledger_entries WHERE {where}")
        ).fetchall()


def test_reissued_ledger_line_with_edited_description_is_not_doubled(client, db_engine, tmp_path, monkeypatch):
    _seed_ibkr_account(db_engine)
    _import(
        db_engine,
        tmp_path,
        monkeypatch,
        _flex_xml("20261001", "20261030", "20261030", _DIVIDEND.format(text="TST Cash Dividend USD 0.10")),
        _flex_xml(
            "20261004",
            "20261102",
            "20261102",
            _DIVIDEND.format(text="TST(US0000000001) Cash Dividend USD 0.10 per Share (Ordinary Dividend)"),
        ),
    )

    rows = _ledger_rows(db_engine, "broker_activity_id = '9000001'")
    assert len(rows) == 1
    assert rows[0][1].startswith("TST(US0000000001)")

    summary = client.get(
        "/dividends/summary",
        params={"from_month": "2026-10", "to_month": "2026-10", "base_currency": "SGD", "period": "month"},
    )
    assert summary.status_code == 200, summary.text
    # 587.99748 is the base fixture's own dividend; the TST one counts once.
    assert round(summary.json()["totals"]["gross"], 5) == round(587.99748 + 25.0, 5)


def test_one_transaction_id_with_two_lines_keeps_both(db_engine, tmp_path, monkeypatch):
    # The same IBKR transaction can show as lines in two currencies; the id is
    # replaced as a group, so both lines stay and a re-import doesn't double them.
    _seed_ibkr_account(db_engine)
    lines = (
        '<StatementOfFundsLine currency="USD" date="20261024" activityCode="DIV" '
        'activityDescription="TST dividend" amount="20.0" transactionID="9000002" />'
        '<StatementOfFundsLine currency="SGD" date="20261024" activityCode="DIV" '
        'activityDescription="TST dividend" amount="26.0" transactionID="9000002" />'
    )
    xml = _flex_xml("20261001", "20261030", "20261030", lines)
    _import(db_engine, tmp_path, monkeypatch, xml, xml)

    rows = _ledger_rows(db_engine, "broker_activity_id = '9000002'")
    assert sorted(float(r[2]) for r in rows) == [20.0, 26.0]


def test_same_id_line_listed_twice_in_one_report_is_stored_once(db_engine, tmp_path, monkeypatch):
    _seed_ibkr_account(db_engine)
    line = _DIVIDEND.format(text="TST Cash Dividend")
    _import(db_engine, tmp_path, monkeypatch, _flex_xml("20261001", "20261030", "20261030", line + line))

    assert len(_ledger_rows(db_engine, "broker_activity_id = '9000001'")) == 1


def _trade(exec_id: str = "") -> str:
    return (
        '<Trade conid="1111" symbol="TST" description="TEST CORP" assetCategory="STK" currency="USD" '
        f'tradeDate="20261022" buySell="BUY" quantity="10" tradePrice="5" proceeds="-50" ibCommission="-1" ibExecID="{exec_id}" />'
    )


def _trades_xml(trades: str) -> str:
    return _flex_xml("20261001", "20261030", "20261030").replace("<Trades />", f"<Trades>{trades}</Trades>")


def _trade_count(db_engine) -> int:
    with db_engine.connect() as conn:
        return int(conn.execute(text("SELECT COUNT(*) FROM portfolio_trades")).scalar())


def test_two_identical_trades_without_execution_id_are_both_kept(db_engine, tmp_path, monkeypatch):
    _seed_ibkr_account(db_engine)
    xml = _trades_xml(_trade() + _trade())
    _import(db_engine, tmp_path, monkeypatch, xml, xml)

    assert _trade_count(db_engine) == 2
    with db_engine.connect() as conn:
        ids = conn.execute(text("SELECT broker_execution_id FROM portfolio_trades")).fetchall()
    assert [r[0] for r in ids] == [None, None]


def test_trade_with_execution_id_is_replaced_by_its_id(db_engine, tmp_path, monkeypatch):
    _seed_ibkr_account(db_engine)
    first = _trades_xml(_trade("EX-1"))
    corrected = _trades_xml(_trade("EX-1").replace('tradePrice="5"', 'tradePrice="5.01"'))
    _import(db_engine, tmp_path, monkeypatch, first, corrected)

    with db_engine.connect() as conn:
        rows = conn.execute(text("SELECT broker_execution_id, price FROM portfolio_trades")).fetchall()
    assert [(r[0], float(r[1])) for r in rows] == [("EX-1", 5.01)]
