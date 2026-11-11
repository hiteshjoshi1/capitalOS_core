"""#399: backup status in the app (U22, D-111), settings facts (U24) and the upload's
account pre-selection (U27). Synthetic data only."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.ingestion.registry import register_signature
from app.ingestion.signature import compute_format_signature
from app.services import backup_status as bs
from app.services.inbox import _backup_items

NOW = datetime(2026, 11, 11, 6, 0, tzinfo=timezone.utc)  # 14:00 in Singapore


def _write(tmp_path: Path, **fields) -> str:
    data = {
        "version": 1,
        "written_at": "2026-11-11T13:05:00+08:00",
        "newest_verified_at": "2026-11-11T13:00:12+08:00",
        "sets": 52,
        "encrypted": True,
        "location": "icloud",
        "daily_time": "13:00",
        "utc_offset": "+08:00",
        "last_run_at": "2026-11-11T13:00:30+08:00",
        "last_run_ok": True,
    }
    data.update(fields)
    path = tmp_path / "backup-status.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


# ---- backup status (U22) ----

def test_no_status_file_means_not_available(tmp_path):
    out = bs.backup_status(now=NOW, path=str(tmp_path / "missing.json"))
    assert out.available is False and out.stale is False


def test_fresh_backup(tmp_path):
    out = bs.backup_status(now=NOW, path=_write(tmp_path))
    assert out.available and not out.stale and not out.very_stale
    assert out.age_hours == 1.0
    assert out.location == "icloud" and out.location_label == "iCloud Drive"
    assert out.sets == 52 and out.encrypted is True and out.last_run_ok is True
    # 14:00 local now, daily at 13:00: the next run is tomorrow 13:00 in the Mac's offset.
    assert out.next_run_at == "2026-11-12T13:00:00+08:00"


def test_next_run_later_today():
    tz = bs._parse_offset("+08:00")
    nxt = bs.next_run_at("13:00", tz, datetime(2026, 11, 11, 1, 0, tzinfo=timezone.utc))  # 09:00 local
    assert nxt is not None and nxt.isoformat() == "2026-11-11T13:00:00+08:00"


def test_stale_after_two_days_and_very_stale_after_seven(tmp_path):
    three_days = bs.backup_status(now=NOW, path=_write(tmp_path, newest_verified_at="2026-11-08T13:00:00+08:00",
                                                       last_run_at="2026-11-08T13:00:00+08:00"))
    assert three_days.stale and not three_days.very_stale
    eight_days = bs.backup_status(now=NOW, path=_write(tmp_path, newest_verified_at="2026-11-03T13:00:00+08:00",
                                                        last_run_at="2026-11-03T13:00:00+08:00"))
    assert eight_days.stale and eight_days.very_stale


def test_a_failed_run_after_the_newest_backup_is_stale(tmp_path):
    out = bs.backup_status(now=NOW, path=_write(tmp_path, last_run_ok=False,
                                                 last_run_at="2026-11-11T13:30:00+08:00",
                                                 newest_verified_at="2026-11-11T09:00:00+08:00"))
    assert out.stale and out.very_stale and out.last_run_ok is False


def test_unknown_values_are_dropped(tmp_path):
    out = bs.backup_status(now=NOW, path=_write(tmp_path, location="/Users/x/secret", daily_time="25:99",
                                                 utc_offset="bad", sets="lots"))
    assert out.location is None and out.daily_time is None and out.next_run_at is None and out.sets is None


def test_endpoint_reads_the_status_file(client, tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_STATUS_FILE", _write(tmp_path))
    resp = client.get("/operations/backup-status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True and body["location_label"] == "iCloud Drive"
    assert "path" not in json.dumps(body).lower() or body.get("location") == "icloud"


def test_endpoint_without_a_status_file(client, tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_STATUS_FILE", str(tmp_path / "none.json"))
    assert client.get("/operations/backup-status").json()["available"] is False


def test_inbox_item_when_stale(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_STATUS_FILE", _write(tmp_path, newest_verified_at="2026-11-01T13:00:00+08:00",
                                                    last_run_at="2026-11-01T13:00:00+08:00"))
    items, good = _backup_items()
    assert good is None and len(items) == 1
    assert items[0].kind == "backup_stale" and items[0].severity == "high"
    assert "make backup-now" in (items[0].detail or "")


def test_inbox_all_good_line_when_fresh(tmp_path, monkeypatch):
    path = _write(tmp_path, newest_verified_at=(datetime.now(timezone.utc) - timedelta(hours=3)).isoformat())
    monkeypatch.setenv("BACKUP_STATUS_FILE", path)
    items, good = _backup_items()
    assert items == [] and good == "Backup verified 3 hours ago"


def test_inbox_nothing_without_a_status_file(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_STATUS_FILE", str(tmp_path / "none.json"))
    assert _backup_items() == ([], None)


# ---- settings facts (U24) ----

def test_settings_facts(client, monkeypatch):
    monkeypatch.setenv("SNAPSHOT_DAY", "1")
    monkeypatch.setenv("UPLOAD_STALE_DAYS", "21")
    body = client.get("/settings/facts").json()
    assert body == {"snapshot_day": 1, "upload_stale_days": 21, "base_currencies": ["SGD", "USD", "HKD", "INR"]}


# ---- upload pre-selection (U27) ----

_DBS_COLUMNS = (
    "Transaction Date,Value Date,Statement Code,Description,Supplementary Code,Supplementary Code Description,"
    "Client Reference,Additional Reference,Status,Currency,Debit Amount,Credit Amount\n"
)


def _dbs_csv(tmp_path: Path, number: str = "012-345678-9") -> Path:
    path = tmp_path / "dbs.csv"
    path.write_text(
        f"Account Details For:,Test Savings {number}\n"
        "Statement as at:,19 Feb 2026\n"
        "Currency:,SGD - Singapore Dollar\n"
        "Available Balance:,SGD 1700.00\n"
        "Ledger Balance:,SGD 1700.00\n" + _DBS_COLUMNS
        + "19 Feb 2026,19 Feb 2026,GR,Test salary,IBG,Payments,REF,OTHR,Settled,SGD,,500\n",
        encoding="utf-8",
    )
    return path


def _seed(db_engine, rows: str) -> None:
    with db_engine.begin() as conn:
        conn.execute(text("INSERT INTO accounts (id, name, platform, user_id, account_type, currency, country) VALUES " + rows))


def _register_dbs(db_engine, path: Path) -> None:
    db = sessionmaker(bind=db_engine)()
    try:
        sig, _ = compute_format_signature(str(path), platform_hint=None)
        register_signature(db, sig, "dbs_transaction_history_csv_v1", 1)
    finally:
        db.close()


def _detect(client, path: Path, name: str | None = None):
    with open(path, "rb") as f:
        return client.post("/ingest/detect", files={"file": (name or path.name, f, "text/csv")})


def test_detect_suggests_the_only_fitting_account(client, db_engine, tmp_path):
    _seed(db_engine, "(3991, 'DBS Savings', 'DBS', 1, 'BANK', 'SGD', 'SG'), "
                     "(3992, 'DBS Card', 'DBS', 1, 'CREDIT_CARD', 'SGD', 'SG'), "
                     "(3993, 'UOB One', 'UOB', 1, 'BANK', 'SGD', 'SG')")
    path = _dbs_csv(tmp_path)
    _register_dbs(db_engine, path)
    body = _detect(client, path).json()
    assert body["recognised"] is True and body["parser_key"] == "dbs_transaction_history_csv_v1"
    assert body["candidate_account_ids"] == [3991] and body["suggested_account_id"] == 3991
    assert body["statement_last4"] == "6789"
    # Nothing was stored or imported.
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM import_jobs")).scalar() == 0


def test_detect_leaves_two_fitting_accounts_to_the_user(client, db_engine, tmp_path):
    _seed(db_engine, "(3994, 'DBS Savings', 'DBS', 1, 'BANK', 'SGD', 'SG'), "
                     "(3995, 'DBS Joint', 'DBS', 1, 'BANK', 'SGD', 'SG')")
    path = _dbs_csv(tmp_path)
    _register_dbs(db_engine, path)
    body = _detect(client, path).json()
    assert body["candidate_account_ids"] == [3994, 3995] and body["suggested_account_id"] is None


def test_detect_unknown_file(client, tmp_path):
    path = tmp_path / "random.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    body = _detect(client, path).json()
    assert body["recognised"] is False and body["suggested_account_id"] is None


def test_detect_other_users_accounts_are_never_suggested(client, db_engine, tmp_path):
    with db_engine.begin() as conn:
        conn.execute(text("INSERT INTO users (id, username, is_active, is_admin) VALUES (3999, 'other399', 1, 0)"))
    _seed(db_engine, "(3996, 'Their DBS', 'DBS', 3999, 'BANK', 'SGD', 'SG')")
    path = _dbs_csv(tmp_path)
    _register_dbs(db_engine, path)
    body = _detect(client, path).json()
    assert 3996 not in body["candidate_account_ids"] and body["suggested_account_id"] is None
