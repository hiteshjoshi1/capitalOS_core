"""This month's uploads (#449, V23): the checklist, its Inbox item and GET /ingest/checklist.
Synthetic data only."""
from __future__ import annotations

from datetime import date

from sqlalchemy import text

from app.services import inbox as ib
from app.services.upload_checklist import monthly_upload_checklist
from tests.auth_helpers import auth_headers, ensure_user

BANK, CARD, BROKER, FLEX, OTHER = 9401, 9402, 9403, 9404, 9405
OTHER_USER = 9450
TODAY = date(2026, 11, 19)


def _freshness_row(account_id, kind, label, last, cadence="monthly", overdue=False):
    return {
        "source_key": f"account:{account_id}", "kind": kind, "label": label, "platform": None,
        "last_data_date": last, "cadence": cadence, "grace_days": 10, "default_cadence": "monthly",
        "default_grace_days": 10, "overridden": cadence != "monthly", "due_date": None,
        "status": "overdue" if overdue else "on_time", "overdue": overdue, "days_overdue": 3 if overdue else None,
    }


def _seed(engine, jobs):
    ensure_user(engine, OTHER_USER, "checklist-other")
    ids = (BANK, CARD, BROKER, FLEX, OTHER)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM import_jobs WHERE id BETWEEN 94000 AND 94999"))
        for a in ids:
            conn.execute(text("DELETE FROM accounts WHERE id = :a"), {"a": a})
        conn.execute(text(
            "INSERT INTO accounts (id, name, platform, account_type, currency, country, user_id) VALUES "
            "(:bank, 'Synthetic Bank', 'DBS', 'BANK', 'SGD', 'SG', 1), "
            "(:card, 'Synthetic Card', 'UOB', 'CREDIT_CARD', 'SGD', 'SG', 1), "
            "(:broker, 'Synthetic Broker', 'SHAREKHAN', 'BROKER', 'INR', 'IN', 1), "
            "(:flex, 'Synthetic Flex', 'IBKR', 'BROKER', 'USD', 'US', 1), "
            "(:other, 'Someone Else', 'DBS', 'BANK', 'SGD', 'SG', :u)"
        ), {"bank": BANK, "card": CARD, "broker": BROKER, "flex": FLEX, "other": OTHER, "u": OTHER_USER})
        for job_id, account, status, created, removed in jobs:
            conn.execute(text(
                "INSERT INTO import_jobs (id, account_id, platform, original_filename, stored_path, file_sha256, "
                "status, created_at, removed_at) VALUES (:id, :a, 'DBS', 'x.csv', '/tmp/x', 'synthetic', :s, :c, :r)"
            ), {"id": job_id, "a": account, "s": status, "c": created, "r": removed})


FRESHNESS = {"sources": [
    _freshness_row(BANK, "bank_statement", "Synthetic Bank", "2026-10-31"),
    _freshness_row(CARD, "card_statement", "Synthetic Card", "2026-10-20", overdue=True),
    _freshness_row(BROKER, "broker_statement", "Synthetic Broker", "2026-11-07"),
    _freshness_row(FLEX, "ibkr_flex", "Synthetic Flex", "2026-11-18", cadence="weekdays"),
    _freshness_row(9499, "bank_statement", "Paused Bank", None, cadence="off"),
    {**_freshness_row(9498, "crypto_wallet", "Wallet", "2026-11-18", cadence="daily"), "source_key": "wallet:x"},
]}


def test_done_by_an_import_this_month_or_data_dated_this_month(db_engine):
    _seed(db_engine, [
        # October's statement uploaded on 3 Nov: done for November although its data is October's.
        (94001, BANK, "IMPORTED", "2026-11-03 02:00:00", None),
        # Card: an October upload, a failed one and a removed one this month don't count.
        (94002, CARD, "IMPORTED", "2026-10-25 02:00:00", None),
        (94003, CARD, "FAILED", "2026-11-05 02:00:00", None),
        (94004, CARD, "IMPORTED", "2026-11-06 02:00:00", "2026-11-07 02:00:00"),
        # Another user's upload to their own account.
        (94005, OTHER, "IMPORTED", "2026-11-04 02:00:00", None),
    ])
    from sqlalchemy.orm import Session

    with Session(db_engine) as db:
        out = monthly_upload_checklist(db, 1, TODAY, FRESHNESS)
    assert (out["month"], out["done"], out["total"]) == ("2026-11", 2, 3)
    rows = {s["account_id"]: s for s in out["sources"]}
    assert set(rows) == {BANK, CARD, BROKER}  # Flex, wallets and a source set to off aren't uploads
    assert rows[BANK]["done"] and rows[BANK]["last_import_date"] == "2026-11-03"
    assert rows[BROKER]["done"] and rows[BROKER]["last_import_date"] is None  # data dated 7 Nov
    assert not rows[CARD]["done"] and rows[CARD]["last_import_date"] == "2026-10-25" and rows[CARD]["overdue"]
    assert out["sources"][0]["account_id"] == CARD  # still to do first


def test_inbox_item_lists_what_is_missing_and_an_all_good_line_when_complete():
    checklist = {"total": 3, "done": 1, "sources": [
        {"label": "UOB Card", "done": False}, {"label": "OCBC", "done": False}, {"label": "DBS", "done": True},
    ]}
    (item,), ok = ib._checklist_items(checklist)
    assert ok is None
    assert (item.kind, item.severity, item.title) == ("monthly_uploads", "low", "This month's uploads: 1 of 3")
    assert item.detail == "Still to upload: UOB Card, OCBC"
    assert (item.action.label, item.action.route) == ("Upload statements", "/ingest")
    assert ib._checklist_items({"total": 2, "done": 2, "sources": []}) == ([], "All 2 statements uploaded this month")
    assert ib._checklist_items({"total": 0, "done": 0, "sources": []}) == ([], None)


def test_checklist_endpoint_is_scoped_to_the_caller(client, db_engine):
    _seed(db_engine, [(94011, BANK, "IMPORTED", "2026-11-03 02:00:00", None)])
    body = client.get("/ingest/checklist").json()
    assert set(body) >= {"month", "done", "total", "sources"}
    ids = {s["account_id"] for s in body["sources"]}
    # No Flex connection here, so the IBKR account is a broker statement to upload like the others.
    assert {BANK, CARD, BROKER, FLEX} <= ids and OTHER not in ids
    assert next(s for s in body["sources"] if s["account_id"] == BANK)["done"] is True
    from fastapi.testclient import TestClient

    from app.main import app

    other = TestClient(app).get("/ingest/checklist", headers=auth_headers(OTHER_USER, "checklist-other")).json()
    assert {s["account_id"] for s in other["sources"]} == {OTHER}
