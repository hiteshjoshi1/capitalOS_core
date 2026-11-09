"""The Data Hub inbox (#316): one list of what needs the user, each with its action.
Synthetic data only. The item builders are tested per kind as pure functions; the
endpoint for an unknown-format upload, an unfinished one, owner scoping and ordering."""
from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import text

from app.services import inbox as ib
from tests.auth_helpers import auth_headers, ensure_user

ACCOUNT = 9101
OTHER_ACCOUNT = 9102
OTHER_USER = 9150


def _row(kind, key, *, status="on_time", overdue=False, days=None, label="Card", last="2026-10-01"):
    return {
        "source_key": key, "kind": kind, "label": label, "platform": None, "last_data_date": last,
        "cadence": "monthly", "grace_days": 5, "default_cadence": "monthly", "default_grace_days": 5,
        "overridden": False, "due_date": None, "status": status, "overdue": overdue, "days_overdue": days,
    }


def test_overdue_sources_get_their_action_and_severity():
    rows = [
        _row("card_statement", "account:7", status="overdue", overdue=True, days=9, label="UOB Card"),
        _row("bank_statement", "account:8", status="overdue", overdue=True, days=2, label="OCBC"),
        _row("ibkr_flex", "account:3", status="overdue", overdue=True, days=1, label="IBKR"),
        _row("crypto_wallet", "wallet:5", status="overdue", overdue=True, days=3, label="Ledger"),
        _row("market_data", "exchange:SGX", status="overdue", overdue=True, days=2, label="SGX quotes"),
        _row("card_statement", "account:9", status="never_loaded", overdue=True, label="Citi", last=None),
        _row("bank_statement", "account:10"),
    ]
    items, on_time = ib._source_items(rows)
    assert on_time == 1
    by_key = {i.id: i for i in items}
    uob = by_key["source:account:7"]
    assert (uob.kind, uob.severity, uob.title) == ("source_overdue", "high", "UOB Card: 9 days overdue")
    assert (uob.action.label, uob.action.route, uob.action.params) == ("Upload", "/ingest", {"account_id": "7"})
    assert uob.source["source_key"] == "account:7"  # the page builds the prefilled link (#278)
    assert by_key["source:account:8"].severity == "medium"
    assert by_key["source:account:3"].action.run == "refresh_ibkr"
    assert by_key["source:account:3"].action.params == {"account_id": "3"}
    assert by_key["source:wallet:5"].action.run == "refresh_crypto"
    sgx = by_key["source:exchange:SGX"].action
    assert (sgx.run, sgx.admin_only) == ("refresh_prices", True)
    citi = by_key["source:account:9"]
    assert (citi.kind, citi.title) == ("source_never_loaded", "Citi: no data yet")


def _summary(*, unpriced=(), jobs=(), fresh=3, stale=0):
    return SimpleNamespace(
        market_data=SimpleNamespace(fresh=fresh, stale=stale, unpriced_holdings=list(unpriced)),
        job_status=list(jobs),
        import_health=SimpleNamespace(pending_count=0, last_import_at="2026-11-01T00:00:00Z"),
        recent_activity=[],
    )


def test_unpriced_holdings_each_get_an_item():
    holding = SimpleNamespace(symbol="ABC", name="Synthetic Co", platform="SHAREKHAN", exchange_code="NSE",
                              currency="INR", reason="no_symbol")
    (item,) = ib._unpriced_items(_summary(unpriced=[holding]))
    assert (item.kind, item.title) == ("unpriced_holding", "ABC: no live price")
    assert item.detail == "SHAREKHAN, NSE; no ticker on a configured exchange"
    assert item.action.route == "/market-data#needs-fix"


def _job(job, state, failures=0, error=None, label="Job"):
    return SimpleNamespace(job=job, label=label, state=state, consecutive_failures=failures, last_error=error)


def test_failing_jobs_are_high_and_healthy_ones_counted():
    items, healthy = ib._job_items(_summary(jobs=[
        _job("ibkr_flex", "failing", 3, "token expired", "IBKR Flex import"),
        _job("market_data", "ok"),
        _job("crypto_refresh", "warning", 1),
    ]))
    assert healthy == 1
    (item,) = items
    assert (item.kind, item.severity, item.title) == ("job_failing", "high", "IBKR Flex import is failing")
    assert item.detail == "3 failed runs in a row: token expired"
    assert item.action.run == "refresh_ibkr"


def test_fx_gap_and_unsupported_currency(monkeypatch):
    plan = SimpleNamespace(uncovered_days=12, unsupported=["VND"], span_start=object())
    monkeypatch.setattr(ib, "plan_backfill", lambda db, uid, base: plan)
    items, ok = ib._fx_items(None, SimpleNamespace(id=1), "SGD")
    assert not ok
    gap, unsupported = items
    assert (gap.kind, gap.title) == ("fx_gap", "Past exchange rates missing for 12 days")
    assert (gap.action.run, gap.action.admin_only) == ("fx_backfill", True)
    assert unsupported.kind == "fx_unsupported" and unsupported.action is None
    monkeypatch.setattr(ib, "plan_backfill", lambda db, uid, base: SimpleNamespace(uncovered_days=0, unsupported=[], span_start=object()))
    assert ib._fx_items(None, SimpleNamespace(id=1), "SGD") == ([], True)


def _seed(engine):
    ensure_user(engine, OTHER_USER, "inbox-other")
    with engine.begin() as conn:
        for job in (91001, 91002, 91003, 91004):
            conn.execute(text("DELETE FROM import_jobs WHERE id = :id"), {"id": job})
        conn.execute(text("DELETE FROM transactions WHERE account_id IN (:a, :b)"), {"a": ACCOUNT, "b": OTHER_ACCOUNT})
        conn.execute(text("DELETE FROM accounts WHERE id IN (:a, :b)"), {"a": ACCOUNT, "b": OTHER_ACCOUNT})
        conn.execute(text(
            "INSERT INTO accounts (id, name, platform, account_type, currency, country, user_id) VALUES "
            "(:a, 'Synthetic Bank', 'DBS', 'BANK', 'SGD', 'SG', 1), "
            "(:b, 'Someone Else', 'DBS', 'BANK', 'SGD', 'SG', :u)"
        ), {"a": ACCOUNT, "b": OTHER_ACCOUNT, "u": OTHER_USER})
        rows = [
            (91001, ACCOUNT, "NEEDS_MAPPING", "odd-export.csv"),
            (91002, ACCOUNT, "VALIDATED", "half.csv"),
            (91003, ACCOUNT, "IMPORTED", "done.csv"),
            (91004, OTHER_ACCOUNT, "NEEDS_MAPPING", "theirs.csv"),
        ]
        for job_id, account, status, name in rows:
            conn.execute(text(
                "INSERT INTO import_jobs (id, account_id, platform, original_filename, stored_path, file_sha256, parser_key, status) "
                "VALUES (:id, :a, 'DBS', :n, '/tmp/x', 'synthetic', NULL, :s)"
            ), {"id": job_id, "a": account, "n": name, "s": status})


def test_inbox_endpoint_names_unknown_formats_and_unfinished_uploads(client, db_engine):
    _seed(db_engine)
    body = client.get("/operations/inbox").json()
    assert body["count"] == len(body["items"])
    by_id = {i["id"]: i for i in body["items"]}
    fmt = by_id["import:91001"]
    assert fmt["kind"] == "unknown_format"
    assert fmt["title"] == "Synthetic Bank: file format not recognised"
    assert fmt["action"] == {"label": "Fix format", "route": "/ingest", "params": {"job": "91001"}, "run": None, "admin_only": False}
    assert by_id["import:91002"]["kind"] == "import_pending"
    assert "import:91003" not in by_id
    assert "import:91004" not in by_id  # another user's upload
    # High first, then medium, then low.
    order = [ib.SEVERITY_ORDER[i["severity"]] for i in body["items"]]
    assert order == sorted(order)


def test_another_user_sees_only_their_own_items(db_engine, client):
    _seed(db_engine)
    from fastapi.testclient import TestClient

    from app.main import app

    other = TestClient(app).get("/operations/inbox", headers=auth_headers(OTHER_USER, "inbox-other")).json()
    ids = {i["id"] for i in other["items"]}
    assert "import:91004" in ids
    assert "import:91001" not in ids and "import:91002" not in ids
