"""Tests for GET /alerts/upload-reminders and GET /alerts/upload-reminders/count."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _days_ago(n: int) -> datetime:
    return datetime.now(tz=timezone.utc) - timedelta(days=n)


# ---------------------------------------------------------------------------
# helpers that insert test data
# ---------------------------------------------------------------------------

def _insert_account(db, account_id: int, name: str, platform: str = "DBS"):
    db.execute(
        text(
            "INSERT OR IGNORE INTO accounts (id, name, platform, account_type, currency) "
            "VALUES (:id, :name, :platform, 'BANK', 'SGD')"
        ),
        {"id": account_id, "name": name, "platform": platform},
    )
    db.commit()


def _insert_import_job(db, job_id: int, account_id: int, status: str, created_at: datetime):
    db.execute(
        text(
            "INSERT OR IGNORE INTO import_jobs "
            "(id, account_id, platform, original_filename, stored_path, file_sha256, status, created_at, updated_at) "
            "VALUES (:id, :account_id, 'DBS', 'f.csv', '/tmp/f', 'sha', :status, :created_at, :created_at)"
        ),
        {
            "id": job_id,
            "account_id": account_id,
            "status": status,
            "created_at": _iso(created_at),
        },
    )
    db.commit()


def _insert_transaction(db, tx_id: int, account_id: int, ts: datetime):
    db.execute(
        text(
            "INSERT OR IGNORE INTO transactions "
            "(id, account_id, ts, amount, type, currency) "
            "VALUES (:id, :account_id, :ts, 100.0, 'EXPENSE', 'SGD')"
        ),
        {"id": tx_id, "account_id": account_id, "ts": _iso(ts)},
    )
    db.commit()


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _cleanup(db_engine):
    """Remove alert-test data after each test."""
    yield
    with db_engine.begin() as conn:
        for aid in (901, 902, 903, 904, 905):
            conn.execute(text("DELETE FROM transactions WHERE account_id = :a"), {"a": aid})
            conn.execute(text("DELETE FROM import_jobs WHERE account_id = :a"), {"a": aid})
            conn.execute(text("DELETE FROM accounts WHERE id = :a"), {"a": aid})


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

class TestUploadReminders:
    def test_stale_account_appears(self, client: TestClient, db_engine):
        """Account with IMPORTED job > 30 days ago is returned."""
        Session = sessionmaker(bind=db_engine)
        db = Session()
        try:
            _insert_account(db, 901, "Stale Account")
            _insert_import_job(db, 9001, 901, "IMPORTED", _days_ago(35))
        finally:
            db.close()

        resp = client.get("/alerts/upload-reminders")
        assert resp.status_code == 200
        data = resp.json()
        ids = [a["account_id"] for a in data]
        assert 901 in ids
        alert = next(a for a in data if a["account_id"] == 901)
        assert alert["days_since_upload"] >= 35
        assert "Stale Account" in alert["message"]
        assert alert["last_upload_date"] is not None

    def test_fresh_account_excluded(self, client: TestClient, db_engine):
        """Account with IMPORTED job < 30 days ago is NOT returned."""
        Session = sessionmaker(bind=db_engine)
        db = Session()
        try:
            _insert_account(db, 902, "Fresh Account")
            _insert_import_job(db, 9002, 902, "IMPORTED", _days_ago(5))
        finally:
            db.close()

        resp = client.get("/alerts/upload-reminders")
        assert resp.status_code == 200
        ids = [a["account_id"] for a in resp.json()]
        assert 902 not in ids

    def test_null_transaction_date_handled(self, client: TestClient, db_engine):
        """Account with no transactions still returns alert; last_transaction_date is None."""
        Session = sessionmaker(bind=db_engine)
        db = Session()
        try:
            _insert_account(db, 903, "No TX Account")
            _insert_import_job(db, 9003, 903, "IMPORTED", _days_ago(40))
        finally:
            db.close()

        resp = client.get("/alerts/upload-reminders")
        assert resp.status_code == 200
        alert = next((a for a in resp.json() if a["account_id"] == 903), None)
        assert alert is not None
        assert alert["last_transaction_date"] is None

    def test_custom_stale_days_env(self, client: TestClient, db_engine, monkeypatch):
        """UPLOAD_STALE_DAYS env override is respected."""
        monkeypatch.setenv("UPLOAD_STALE_DAYS", "10")
        Session = sessionmaker(bind=db_engine)
        db = Session()
        try:
            _insert_account(db, 904, "Semi-Stale Account")
            _insert_import_job(db, 9004, 904, "IMPORTED", _days_ago(15))
        finally:
            db.close()

        resp = client.get("/alerts/upload-reminders")
        assert resp.status_code == 200
        ids = [a["account_id"] for a in resp.json()]
        assert 904 in ids

    def test_no_imports_excludes_account(self, client: TestClient, db_engine):
        """Account with no IMPORTED jobs (only FAILED) is never shown."""
        Session = sessionmaker(bind=db_engine)
        db = Session()
        try:
            _insert_account(db, 905, "Never Imported")
            _insert_import_job(db, 9005, 905, "FAILED", _days_ago(60))
        finally:
            db.close()

        resp = client.get("/alerts/upload-reminders")
        assert resp.status_code == 200
        ids = [a["account_id"] for a in resp.json()]
        assert 905 not in ids

    def test_count_matches_reminders(self, client: TestClient, db_engine):
        """Count endpoint returns the same number as the full list."""
        Session = sessionmaker(bind=db_engine)
        db = Session()
        try:
            _insert_account(db, 901, "Stale Account")
            _insert_import_job(db, 9001, 901, "IMPORTED", _days_ago(35))
        finally:
            db.close()

        full = client.get("/alerts/upload-reminders").json()
        count_resp = client.get("/alerts/upload-reminders/count").json()
        assert count_resp["count"] == len(full)

    def test_alert_schema_fields(self, client: TestClient, db_engine):
        """Each alert contains all required fields."""
        Session = sessionmaker(bind=db_engine)
        db = Session()
        try:
            _insert_account(db, 901, "Stale Account")
            _insert_import_job(db, 9001, 901, "IMPORTED", _days_ago(35))
            _insert_transaction(db, 99001, 901, _days_ago(36))
        finally:
            db.close()

        resp = client.get("/alerts/upload-reminders")
        assert resp.status_code == 200
        alert = next((a for a in resp.json() if a["account_id"] == 901), None)
        assert alert is not None
        for field in ("account_id", "account_name", "platform", "account_type",
                      "last_upload_date", "last_transaction_date", "days_since_upload", "message"):
            assert field in alert, f"Missing field: {field}"
