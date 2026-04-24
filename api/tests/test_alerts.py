"""Tests for alerts endpoints: upload-reminders, notifications, and pruning."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.models.rag import RealtimeEvent, RagAuthor, RagSource, RagIngestionJob
from app.services.alerts import prune_old_realtime_events
from tests.conftest import TestingSessionLocal


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


# ---------------------------------------------------------------------------
# helpers for system notification tests
# ---------------------------------------------------------------------------

def _insert_realtime_event(
    user_id: int,
    event_name: str,
    author_id: str,
    created_at: datetime,
    status: str = "done",
) -> RealtimeEvent:
    db = TestingSessionLocal()
    try:
        event = RealtimeEvent(
            user_id=user_id,
            topic="author-ingestion",
            event_name=event_name,
            author_id=author_id,
            status=status,
            payload={
                "author": {"id": author_id, "name": author_id},
                "batch": {"id": None, "status": status},
                "source": {"url": f"https://example.com/{author_id}", "author_id": author_id},
                "job": {"error": None, "status": status},
            },
            created_at=created_at,
        )
        db.add(event)
        db.commit()
        db.refresh(event)
        return event
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Tests for GET /alerts/notifications
# ---------------------------------------------------------------------------

class TestUnifiedNotifications:
    @pytest.fixture(autouse=True)
    def _cleanup_events(self, db_engine):
        yield
        with db_engine.begin() as conn:
            conn.execute(text("DELETE FROM realtime_events WHERE user_id = 1"))

    def test_notifications_returns_upload_reminders(self, client: TestClient, db_engine):
        """Unified notifications endpoint includes stale upload reminders."""
        Session = sessionmaker(bind=db_engine)
        db = Session()
        try:
            _insert_account(db, 901, "Stale Account")
            _insert_import_job(db, 9001, 901, "IMPORTED", _days_ago(35))
        finally:
            db.close()

        resp = client.get("/alerts/notifications")
        assert resp.status_code == 200
        data = resp.json()
        assert "upload_reminders" in data
        assert "system_notifications" in data
        assert "total_count" in data
        ids = [r["account_id"] for r in data["upload_reminders"]]
        assert 901 in ids

    def test_notifications_includes_system_events(self, client: TestClient, db_engine):
        """Unified notifications endpoint returns realtime events as system notifications."""
        _insert_realtime_event(
            user_id=1,
            event_name="batch_completed",
            author_id="test_author",
            created_at=_days_ago(1),
        )

        resp = client.get("/alerts/notifications")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["system_notifications"]) >= 1
        notif = data["system_notifications"][0]
        for field in ("id", "alert_type", "topic", "event_name", "message", "created_at"):
            assert field in notif, f"Missing field: {field}"
        assert notif["alert_type"] == "system_notification"
        assert "test_author" in notif["message"]

    def test_notifications_total_count_is_sum(self, client: TestClient, db_engine):
        """total_count equals len(upload_reminders) + len(system_notifications)."""
        Session = sessionmaker(bind=db_engine)
        db = Session()
        try:
            _insert_account(db, 901, "Stale Account")
            _insert_import_job(db, 9001, 901, "IMPORTED", _days_ago(35))
        finally:
            db.close()

        _insert_realtime_event(
            user_id=1,
            event_name="source_ingested",
            author_id="test_author",
            created_at=_days_ago(2),
        )

        resp = client.get("/alerts/notifications")
        data = resp.json()
        assert data["total_count"] == len(data["upload_reminders"]) + len(data["system_notifications"])

    def test_system_notification_message_formats(self, client: TestClient, db_engine):
        """Each event_name produces a sensible human-readable message."""
        for event_name in ("batch_submitted", "source_queued", "source_running", "source_ingested", "source_failed", "batch_completed"):
            _insert_realtime_event(
                user_id=1,
                event_name=event_name,
                author_id="buffett",
                created_at=_days_ago(1),
            )

        resp = client.get("/alerts/notifications")
        assert resp.status_code == 200
        messages = [n["message"] for n in resp.json()["system_notifications"]]
        # All messages must be non-empty
        assert all(m for m in messages)

    def test_notifications_empty_when_no_data(self, client: TestClient, db_engine):
        """Returns empty lists when no reminders and no events."""
        resp = client.get("/alerts/notifications")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["upload_reminders"], list)
        assert isinstance(data["system_notifications"], list)
        assert data["total_count"] == len(data["upload_reminders"]) + len(data["system_notifications"])

    def test_notifications_author_fields_populated(self, client: TestClient, db_engine):
        """System notifications include author_id when available."""
        _insert_realtime_event(
            user_id=1,
            event_name="source_ingested",
            author_id="charlie_munger",
            created_at=_days_ago(3),
        )

        resp = client.get("/alerts/notifications")
        notifs = resp.json()["system_notifications"]
        charlie_notifs = [n for n in notifs if n.get("author_id") == "charlie_munger"]
        assert len(charlie_notifs) >= 1


# ---------------------------------------------------------------------------
# Tests for POST /alerts/prune (retention policy)
# ---------------------------------------------------------------------------

class TestAlertsRetentionPruning:
    @pytest.fixture(autouse=True)
    def _cleanup_events(self, db_engine):
        yield
        with db_engine.begin() as conn:
            conn.execute(text("DELETE FROM realtime_events WHERE user_id = 1"))

    def test_prune_removes_old_events(self, db_engine):
        """prune_old_realtime_events deletes events older than 180 days."""
        # Insert one old event (200 days ago) and one recent event (10 days ago)
        _insert_realtime_event(
            user_id=1,
            event_name="batch_completed",
            author_id="old_author",
            created_at=_days_ago(200),
        )
        _insert_realtime_event(
            user_id=1,
            event_name="source_ingested",
            author_id="recent_author",
            created_at=_days_ago(10),
        )

        db = TestingSessionLocal()
        try:
            deleted = prune_old_realtime_events(db)
        finally:
            db.close()

        assert deleted >= 1

        # Verify the recent event still exists
        db2 = TestingSessionLocal()
        try:
            remaining = db2.query(RealtimeEvent).filter(
                RealtimeEvent.user_id == 1,
                RealtimeEvent.author_id == "recent_author",
            ).all()
            assert len(remaining) == 1, "Recent event must not be pruned"

            pruned = db2.query(RealtimeEvent).filter(
                RealtimeEvent.user_id == 1,
                RealtimeEvent.author_id == "old_author",
            ).all()
            assert len(pruned) == 0, "Old event must be pruned"
        finally:
            db2.close()

    def test_prune_does_not_remove_recent_events(self, db_engine):
        """prune_old_realtime_events does NOT delete events within 180 days."""
        _insert_realtime_event(
            user_id=1,
            event_name="source_ingested",
            author_id="fresh_author",
            created_at=_days_ago(5),
        )

        db = TestingSessionLocal()
        try:
            deleted = prune_old_realtime_events(db)
        finally:
            db.close()

        db2 = TestingSessionLocal()
        try:
            remaining = db2.query(RealtimeEvent).filter(
                RealtimeEvent.user_id == 1,
                RealtimeEvent.author_id == "fresh_author",
            ).all()
            assert len(remaining) == 1, "Recent event must still exist after pruning"
        finally:
            db2.close()

    def test_prune_endpoint_returns_deleted_count(self, client: TestClient, db_engine):
        """POST /alerts/prune returns the number of deleted records."""
        _insert_realtime_event(
            user_id=1,
            event_name="batch_completed",
            author_id="expire_author",
            created_at=_days_ago(200),
        )

        resp = client.post("/alerts/prune")
        assert resp.status_code == 200
        data = resp.json()
        assert "deleted" in data
        assert data["deleted"] >= 1
        assert data["retention_days"] == 180

    def test_prune_endpoint_when_nothing_to_prune(self, client: TestClient, db_engine):
        """POST /alerts/prune returns 0 when no expired events exist."""
        _insert_realtime_event(
            user_id=1,
            event_name="source_ingested",
            author_id="new_author",
            created_at=_days_ago(1),
        )

        resp = client.post("/alerts/prune")
        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted"] == 0

