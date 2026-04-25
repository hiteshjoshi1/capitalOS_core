"""
Tests for Issue 147: RAG Author Ingestion UI endpoints.

Uses the shared conftest.py SQLite engine (same pattern as test_rag.py).

Covers:
  - POST /rag/authors — create author from UI
  - POST /rag/authors (duplicate) — 409
  - POST /rag/authors/{id}/ingest-urls — register multiple URLs
  - POST /rag/authors/{id}/ingest-urls — deduplicate already-registered URLs
  - GET /rag/ingest/jobs — filter by author_id
  - POST /rag/ingest/retry/{source_id} — retry queues a new job
"""

from __future__ import annotations

import os
import uuid

import pytest

# Must be set before importing app modules; conftest.py sets DATABASE_URL but
# we ensure RAG mocking is on so no real embeddings are attempted.
os.environ.setdefault("RAG_EMBEDDING_MOCK", "1")
os.environ.setdefault("AUTH_BYPASS_USER_ID", "1")

# conftest.py at session scope runs Base.metadata.create_all and injects
# TestingSessionLocal via app.dependency_overrides[get_db], so all we need
# here is the `client` fixture from conftest + access to the session.

from tests.conftest import TestingSessionLocal  # noqa: E402  # imported for direct DB access


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _make_author(client, *, id_suffix: str | None = None, **kwargs):
    """POST /rag/authors and assert 201. Returns response data."""
    aid = f"test_{id_suffix or _uid()}"
    payload = {"id": aid, "name": f"Test Author {aid}", "enabled": True, **kwargs}
    resp = client.post("/rag/authors", json=payload)
    assert resp.status_code == 201, f"create_author failed: {resp.text}"
    return resp.json()


# ─────────────────────────────────────────────────────────────────────────────
# Author creation
# ─────────────────────────────────────────────────────────────────────────────


class TestCreateAuthor:
    def test_create_author_minimal(self, client):
        """POST /rag/authors with required fields creates a new author."""
        aid = f"ui_{_uid()}"
        resp = client.post("/rag/authors", json={"id": aid, "name": "UI Test Author", "enabled": True})
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["id"] == aid
        assert data["name"] == "UI Test Author"
        assert data["enabled"] is True
        assert data["domains"] == []
        assert data["expertise_tags"] == []
        assert data["overall_weight"] == 1.0
        assert data["role_type"] is None

    def test_create_author_with_advanced_fields(self, client):
        """POST /rag/authors with optional metadata fields persists them."""
        aid = f"adv_{_uid()}"
        payload = {
            "id": aid,
            "name": "Advanced Author",
            "enabled": False,
            "domains": ["investing", "business"],
            "expertise_tags": ["value", "moat"],
            "overall_weight": 2.5,
            "role_type": "investor",
        }
        resp = client.post("/rag/authors", json=payload)
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["domains"] == ["investing", "business"]
        assert data["expertise_tags"] == ["value", "moat"]
        assert data["overall_weight"] == 2.5
        assert data["role_type"] == "investor"
        assert data["enabled"] is False

    def test_create_author_duplicate_returns_409(self, client):
        """POST /rag/authors with an existing id returns 409."""
        aid = f"dup_{_uid()}"
        resp = client.post("/rag/authors", json={"id": aid, "name": "First", "enabled": True})
        assert resp.status_code == 201
        resp2 = client.post("/rag/authors", json={"id": aid, "name": "Second", "enabled": True})
        assert resp2.status_code == 409
        assert aid in resp2.json()["detail"]

    def test_create_author_invalid_id_pattern_returns_422(self, client):
        """POST /rag/authors with uppercase id returns 422."""
        resp = client.post("/rag/authors", json={"id": "BadSlug", "name": "Test", "enabled": True})
        assert resp.status_code == 422

    def test_created_author_appears_in_list(self, client):
        """Author created via POST /rag/authors is visible in GET /rag/authors."""
        aid = f"list_{_uid()}"
        client.post("/rag/authors", json={"id": aid, "name": "List Check", "enabled": True})
        resp = client.get("/rag/authors")
        assert resp.status_code == 200
        ids = [a["id"] for a in resp.json()]
        assert aid in ids


# ─────────────────────────────────────────────────────────────────────────────
# Multi-URL registration and background ingestion kickoff
# ─────────────────────────────────────────────────────────────────────────────


class TestIngestUrls:
    @pytest.fixture(autouse=True)
    def fresh_author(self, client):
        """Create a fresh author for each test."""
        data = _make_author(client)
        self.author_id = data["id"]

    def test_register_single_url(self, client):
        """POST ingest-urls with one URL registers the source and queues a job."""
        url = f"https://example.com/article-{_uid()}"
        resp = client.post(f"/rag/authors/{self.author_id}/ingest-urls", json={"urls": [url], "source_type": "html"})
        assert resp.status_code == 202, resp.text
        data = resp.json()
        assert data["author_id"] == self.author_id
        assert data["registered"] == 1
        assert data["skipped_duplicate"] == 0
        assert data["jobs_queued"] == 1
        assert len(data["sources"]) == 1
        assert len(data["job_ids"]) == 1
        assert data["sources"][0]["url"] == url
        # Status is queued until the background worker starts.
        assert data["sources"][0]["status"] in {"queued", "running", "ingested", "failed"}

    def test_register_multiple_urls(self, client):
        """POST ingest-urls with multiple URLs registers all of them."""
        urls = [f"https://example.com/a-{_uid()}", f"https://example.com/b-{_uid()}", f"https://example.com/c-{_uid()}"]
        resp = client.post(f"/rag/authors/{self.author_id}/ingest-urls", json={"urls": urls, "source_type": "html"})
        assert resp.status_code == 202, resp.text
        data = resp.json()
        assert data["registered"] == 3
        assert data["jobs_queued"] == 3

    def test_requeues_already_registered_url_when_not_running(self, client):
        """POST ingest-urls requeues an existing URL and updates the existing source."""
        url = f"https://example.com/dedup-{_uid()}"
        # First registration
        r1 = client.post(f"/rag/authors/{self.author_id}/ingest-urls", json={"urls": [url], "source_type": "html"})
        assert r1.status_code == 202
        assert r1.json()["registered"] == 1

        # Second registration with same URL + one new URL
        new_url = f"https://example.com/new-{_uid()}"
        r2 = client.post(f"/rag/authors/{self.author_id}/ingest-urls", json={"urls": [url, new_url], "source_type": "html"})
        assert r2.status_code == 202
        data = r2.json()
        assert data["registered"] == 1
        assert data["requeued_existing"] == 1
        assert data["skipped_duplicate"] == 0
        assert data["jobs_queued"] == 2

    def test_author_not_found_returns_404(self, client):
        """POST ingest-urls for a non-existent author returns 404."""
        resp = client.post("/rag/authors/nonexistent_xyz_000/ingest-urls", json={"urls": ["https://example.com/x"], "source_type": "html"})
        assert resp.status_code == 404

    def test_blank_urls_are_skipped(self, client):
        """POST ingest-urls with only whitespace/blank URLs returns 202 with 0 registered."""
        resp = client.post(f"/rag/authors/{self.author_id}/ingest-urls", json={"urls": ["   "], "source_type": "html"})
        assert resp.status_code == 202
        data = resp.json()
        assert data["registered"] == 0
        assert data["jobs_queued"] == 0

    def test_sources_visible_after_registration(self, client):
        """GET /rag/sources?author_id= shows sources registered via ingest-urls."""
        url = f"https://example.com/visible-{_uid()}"
        client.post(f"/rag/authors/{self.author_id}/ingest-urls", json={"urls": [url], "source_type": "html"})
        resp = client.get(f"/rag/sources?author_id={self.author_id}")
        assert resp.status_code == 200
        registered_urls = [s["url"] for s in resp.json()]
        assert url in registered_urls

    def test_ingestion_activity_returns_durable_events_for_reload_recovery(self, client):
        """GET /rag/ingest/activity returns durable backend state and lifecycle events."""
        url = f"https://example.com/activity-{_uid()}"
        ingest_resp = client.post(
            f"/rag/authors/{self.author_id}/ingest-urls",
            json={"urls": [url], "source_type": "html"},
        )
        assert ingest_resp.status_code == 202, ingest_resp.text
        source_id = ingest_resp.json()["sources"][0]["id"]

        activity_resp = client.get(f"/rag/ingest/activity?author_id={self.author_id}")
        assert activity_resp.status_code == 200, activity_resp.text
        activity = activity_resp.json()

        assert any(source["url"] == url for source in activity["sources"])
        assert any(job["source_id"] == source_id for job in activity["jobs"])

        batch_events = [
            event
            for event in activity["events"]
            if event["payload"].get("source", {}).get("url") == url or event["payload"].get("author", {}).get("id") == self.author_id
        ]
        event_names = {event["event_name"] for event in batch_events}
        assert "batch_submitted" in event_names
        assert "source_queued" in event_names

        queued_event = next(event for event in batch_events if event["event_name"] == "source_queued")
        assert queued_event["author_id"] == self.author_id
        assert queued_event["source_id"]
        assert queued_event["job_id"]
        assert queued_event["status"] == "queued"
        assert queued_event["payload"]["author"]["id"] == self.author_id
        assert queued_event["payload"]["source"]["url"] == url


# ─────────────────────────────────────────────────────────────────────────────
# Job status retrieval by author_id
# ─────────────────────────────────────────────────────────────────────────────


class TestJobStatusByAuthor:
    @pytest.fixture(autouse=True)
    def author_with_queued_job(self, client):
        """Create an author and register one URL so a queued job exists."""
        data = _make_author(client)
        self.author_id = data["id"]
        url = f"https://example.com/job-{_uid()}"
        client.post(f"/rag/authors/{self.author_id}/ingest-urls", json={"urls": [url], "source_type": "html"})

    def test_list_jobs_filtered_by_author_id(self, client):
        """GET /rag/ingest/jobs?author_id= returns only jobs for that author."""
        resp = client.get(f"/rag/ingest/jobs?author_id={self.author_id}")
        assert resp.status_code == 200
        jobs = resp.json()
        assert len(jobs) >= 1
        # Cross-check: all returned jobs should belong to sources of this author
        sources_resp = client.get(f"/rag/sources?author_id={self.author_id}")
        source_ids = {s["id"] for s in sources_resp.json()}
        for job in jobs:
            assert job["source_id"] in source_ids

    def test_new_job_has_valid_status(self, client):
        """Jobs created by ingest-urls have a valid status field."""
        resp = client.get(f"/rag/ingest/jobs?author_id={self.author_id}")
        assert resp.status_code == 200
        for job in resp.json():
            assert job["status"] in {"queued", "running", "done", "failed"}


# ─────────────────────────────────────────────────────────────────────────────
# Retry flow
# ─────────────────────────────────────────────────────────────────────────────


class TestRetryIngestion:
    @pytest.fixture(autouse=True)
    def failed_source(self, client):
        """Create an author, register a URL, then mark the source as failed."""
        from app.models.rag import RagSource

        data = _make_author(client)
        self.author_id = data["id"]

        url = f"https://example.com/retry-{_uid()}"
        ingest_resp = client.post(
            f"/rag/authors/{self.author_id}/ingest-urls",
            json={"urls": [url], "source_type": "html"},
        )
        assert ingest_resp.status_code == 202
        self.source_id = ingest_resp.json()["sources"][0]["id"]

        # Mark the source as failed directly in the DB
        db = TestingSessionLocal()
        try:
            source = db.get(RagSource, self.source_id)
            assert source is not None
            source.status = "failed"
            db.commit()
        finally:
            db.close()

    def test_retry_returns_202_with_job(self, client):
        """POST /rag/ingest/retry/{source_id} returns 202 and a queued/running job."""
        resp = client.post(f"/rag/ingest/retry/{self.source_id}")
        assert resp.status_code == 202, resp.text
        job = resp.json()
        assert job["source_id"] == self.source_id
        assert job["status"] in {"queued", "running", "done", "failed"}
        assert job["batch_id"]

        activity_resp = client.get(f"/rag/ingest/activity?author_id={self.author_id}")
        assert activity_resp.status_code == 200, activity_resp.text
        activity = activity_resp.json()

        retry_events = [event for event in activity["events"] if event["batch_id"] == job["batch_id"]]
        retry_event_names = {event["event_name"] for event in retry_events}
        assert "batch_submitted" in retry_event_names
        assert "source_queued" in retry_event_names

    def test_retry_on_source_without_url_returns_422(self, client):
        """POST /rag/ingest/retry for a source with no URL returns 422."""
        from app.models.rag import RagSource

        db = TestingSessionLocal()
        try:
            no_url_source = RagSource(
                user_id=1,
                author_id=self.author_id,
                url=None,
                source_type="manual",
                status="failed",
            )
            db.add(no_url_source)
            db.commit()
            db.refresh(no_url_source)
            source_id = str(no_url_source.id)
        finally:
            db.close()

        resp = client.post(f"/rag/ingest/retry/{source_id}")
        assert resp.status_code == 422
