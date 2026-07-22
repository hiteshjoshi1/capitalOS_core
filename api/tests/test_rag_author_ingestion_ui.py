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
import json
from unittest.mock import patch

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

    def test_ingest_urls_persists_fanout_ingestion_config(self, client):
        """POST ingest-urls accepts and stores deterministic fanout configuration."""
        override_author = _make_author(client, id_suffix=f"override_{_uid()}")
        url = f"https://example.com/compendium-{_uid()}"
        payload = {
            "urls": [url],
            "source_type": "html",
            "ingestion_config": {
                "mode": "fanout",
                "documents": [
                    {
                        "key": "essay-a",
                        "title": "Essay A",
                        "author_id": override_author["id"],
                        "publication_year": 2024,
                        "venue": "Letters",
                        "collection": "Collected Letters",
                        "canonical_work_id": "essay-a",
                        "canonical_status": "canonical",
                        "dedupe_priority": 10,
                        "source_section": "Essay A",
                        "work_type": "essay",
                        "metadata": {"edition": "first"},
                        "selective_ingestion": {"include_headings": ["Essay A"]},
                    }
                ],
            },
        }

        resp = client.post(f"/rag/authors/{self.author_id}/ingest-urls", json=payload)
        assert resp.status_code == 202, resp.text
        source = resp.json()["sources"][0]
        assert source["ingestion_config"]["mode"] == "fanout"
        assert source["ingestion_config"]["documents"][0]["key"] == "essay-a"
        assert source["ingestion_config"]["documents"][0]["author_id"] == override_author["id"]
        assert source["ingestion_config"]["documents"][0]["selective_options"]["include_headings"] == ["Essay A"]

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


class TestFanoutConfigApis:
    def test_preview_returns_logical_documents_and_metadata(self, client):
        source_author = _make_author(client, id_suffix=f"source_{_uid()}")
        override_author = _make_author(client, id_suffix=f"override_{_uid()}")
        resp = client.post(
            "/rag/fanout/preview",
            json={
                "author_id": source_author["id"],
                "source_title": "Collected Writings",
                "source_published_at": "2024-04-01",
                "ingestion_config": {
                    "mode": "fanout",
                    "documents": [
                        {
                            "key": "letter-1",
                            "title": "Letter 1",
                            "author_id": override_author["id"],
                            "collection": "Collected Writings",
                            "canonical_work_id": "letter-1",
                            "canonical_status": "canonical",
                            "source_section": "Letter 1",
                            "work_type": "letter",
                            "metadata": {"topic": "quality"},
                            "canonical_metadata": {"edition": "annotated"},
                            "selective_ingestion": {"include_headings": ["Letter 1"]},
                        },
                        {
                            "key": "letter-1-notes",
                            "title": "Letter 1 Notes",
                            "parent_key": "letter-1",
                            "note_taker": "Archivist",
                            "work_type": "notes",
                            "selective_ingestion": {"include_headings": ["Letter 1 Notes"]},
                        },
                    ],
                },
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["mode"] == "fanout"
        assert body["document_count"] == 2
        primary, notes = body["documents"]
        assert primary["author_id"] == override_author["id"]
        assert primary["canonical_work_id"] == "letter-1"
        assert primary["metadata"]["topic"] == "quality"
        assert primary["metadata"]["canonical_metadata"]["edition"] == "annotated"
        assert primary["selective_ingestion"]["include_headings"] == ["Letter 1"]
        assert notes["parent_key"] == "letter-1"
        assert notes["note_taker"] == "Archivist"

    def test_preview_rejects_unknown_parent_key(self, client):
        source_author = _make_author(client, id_suffix=f"source_{_uid()}")
        resp = client.post(
            "/rag/fanout/preview",
            json={
                "author_id": source_author["id"],
                "ingestion_config": {
                    "mode": "fanout",
                    "documents": [
                        {
                            "key": "child",
                            "title": "Child",
                            "parent_key": "missing-parent",
                        }
                    ],
                },
            },
        )
        assert resp.status_code == 422
        assert "unknown parent" in resp.json()["detail"]

    def test_patch_source_ingestion_config_updates_existing_source(self, client):
        author = _make_author(client, id_suffix=f"patch_{_uid()}")
        source_resp = client.post(
            "/rag/sources",
            json={
                "author_id": author["id"],
                "url": f"https://example.com/source-{_uid()}",
                "source_type": "html",
            },
        )
        assert source_resp.status_code == 201, source_resp.text
        source_id = source_resp.json()["id"]

        patch_resp = client.patch(
            f"/rag/sources/{source_id}/ingestion-config",
            json={
                "ingestion_config": {
                    "mode": "fanout",
                    "documents": [
                        {
                            "key": "doc-1",
                            "title": "Doc 1",
                            "collection": "Compendium",
                            "source_section": "Doc 1",
                            "selective_ingestion": {"include_headings": ["Doc 1"]},
                        }
                    ],
                }
            },
        )
        assert patch_resp.status_code == 200, patch_resp.text
        assert patch_resp.json()["ingestion_config"]["mode"] == "fanout"

        sources_resp = client.get(f"/rag/sources?author_id={author['id']}")
        assert sources_resp.status_code == 200, sources_resp.text
        updated = next(source for source in sources_resp.json() if source["id"] == source_id)
        assert updated["ingestion_config"]["documents"][0]["source_section"] == "Doc 1"


class TestPdfUploadIngestion:
    def test_pdf_upload_stores_source_url_and_ingestion_config(self, client):
        from app.models.rag import RagIngestionJob

        author = _make_author(client, id_suffix=f"pdf_{_uid()}")
        captured = {}

        def fake_run_pdf_bytes_ingestion(source, raw_bytes, db, *, title=None, published_at=None, filename=None):
            captured["source_type"] = source.source_type
            captured["source_url"] = source.url
            captured["raw_bytes"] = raw_bytes
            captured["title"] = title
            captured["published_at"] = published_at.isoformat() if published_at else None
            captured["filename"] = filename
            source.hash = "fake-pdf-hash"
            source.status = "ingested"
            job = RagIngestionJob(
                user_id=source.user_id,
                source_id=source.id,
                status="done",
                stats_json={"documents_created": 1},
            )
            db.add(job)
            db.flush()
            return job

        ingestion_config = {
            "mode": "fanout",
            "documents": [
                {
                    "key": "mauboussin-test",
                    "title": "Mauboussin Test",
                    "published_at": "2026-06-18",
                    "publication_year": 2026,
                    "collection": "Consilient Observer",
                    "work_type": "article",
                }
            ],
        }

        with patch("app.routers.rag.run_pdf_bytes_ingestion", side_effect=fake_run_pdf_bytes_ingestion):
            resp = client.post(
                "/rag/ingest/pdf/upload",
                data={
                    "author_id": author["id"],
                    "title": "Mauboussin Test",
                    "published_at": "2026-06-18",
                    "source_url": "https://www.morganstanley.com/example.pdf",
                    "ingestion_config_json": json.dumps(ingestion_config),
                },
                files={"file": ("example.pdf", b"%PDF-1.7\nfake", "application/pdf")},
            )

        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["status"] == "done"
        assert captured == {
            "source_type": "pdf",
            "source_url": "https://www.morganstanley.com/example.pdf",
            "raw_bytes": b"%PDF-1.7\nfake",
            "title": "Mauboussin Test",
            "published_at": "2026-06-18",
            "filename": "example.pdf",
        }

        sources_resp = client.get(f"/rag/sources?author_id={author['id']}")
        assert sources_resp.status_code == 200, sources_resp.text
        source = next(source for source in sources_resp.json() if source["url"] == "https://www.morganstanley.com/example.pdf")
        assert source["source_type"] == "pdf"
        assert source["status"] == "ingested"
        assert source["ingestion_config"]["documents"][0]["collection"] == "Consilient Observer"

    def test_pdf_upload_rejects_non_pdf_bytes(self, client):
        author = _make_author(client, id_suffix=f"pdf_bad_{_uid()}")
        resp = client.post(
            "/rag/ingest/pdf/upload",
            data={"author_id": author["id"]},
            files={"file": ("not.pdf", b"not a pdf", "application/pdf")},
        )
        assert resp.status_code == 422
        assert "does not look like a PDF" in resp.json()["detail"]

    def test_pdf_upload_reuses_existing_failed_source_by_url(self, client):
        """
        A URL that already failed automatic fetch (e.g. HTTP 403) should be
        reused, not duplicated, when the user falls back to a manual upload
        for that same URL — same dedupe behavior as ingest-urls.
        """
        author = _make_author(client, id_suffix=f"pdf_dedupe_{_uid()}")
        blocked_url = "https://www.morganstanley.com/example-blocked.pdf"

        register_resp = client.post(
            f"/rag/authors/{author['id']}/ingest-urls",
            json={"urls": [blocked_url], "source_type": "pdf"},
        )
        assert register_resp.status_code == 202, register_resp.text
        original_source_id = register_resp.json()["sources"][0]["id"]

        from app.models.rag import RagIngestionJob

        def fake_run_pdf_bytes_ingestion(source, raw_bytes, db, **kwargs):
            source.status = "ingested"
            job = RagIngestionJob(user_id=source.user_id, source_id=source.id, status="done", stats_json={})
            db.add(job)
            db.flush()
            return job

        with patch(
            "app.routers.rag.run_pdf_bytes_ingestion",
            side_effect=fake_run_pdf_bytes_ingestion,
        ):
            upload_resp = client.post(
                "/rag/ingest/pdf/upload",
                data={"author_id": author["id"], "source_url": blocked_url},
                files={"file": ("example.pdf", b"%PDF-1.7\nfake", "application/pdf")},
            )
        assert upload_resp.status_code == 202, upload_resp.text

        sources_resp = client.get(f"/rag/sources?author_id={author['id']}")
        matching = [s for s in sources_resp.json() if s["url"] == blocked_url]
        assert len(matching) == 1, f"expected exactly one source for {blocked_url}, got {matching}"
        assert matching[0]["id"] == original_source_id
        assert matching[0]["source_type"] == "pdf"
        assert matching[0]["status"] == "ingested"

    def test_pdf_upload_persists_raw_bytes_for_later_retrieval(self, client):
        """
        The uploaded PDF bytes must survive ingestion so the document can be
        opened later via GET /rag/sources/{id}/file — even when the host that
        originally served it stays unreachable. Uses the real (unmocked)
        run_pdf_bytes_ingestion so this exercises the actual persistence path,
        not a stand-in.
        """
        author = _make_author(client, id_suffix=f"pdf_store_{_uid()}")
        pdf_bytes = (
            b"%PDF-1.4\n"
            b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/MediaBox[0 0 3 3]>>endobj\n"
            b"xref\n0 4\n"
            b"0000000000 65535 f \n"
            b"0000000009 00000 n \n"
            b"0000000058 00000 n \n"
            b"0000000115 00000 n \n"
            b"trailer<</Size 4/Root 1 0 R>>\n"
            b"startxref\n190\n%%EOF"
        )

        upload_resp = client.post(
            "/rag/ingest/pdf/upload",
            data={"author_id": author["id"]},
            files={"file": ("mauboussin.pdf", pdf_bytes, "application/pdf")},
        )
        assert upload_resp.status_code == 202, upload_resp.text
        source_id = upload_resp.json()["source_id"]

        file_resp = client.get(f"/rag/sources/{source_id}/file")
        assert file_resp.status_code == 200, file_resp.text
        assert file_resp.content == pdf_bytes
        assert file_resp.headers["content-type"] == "application/pdf"
        assert "mauboussin.pdf" in file_resp.headers["content-disposition"]

    def test_get_source_file_404_when_no_stored_file(self, client):
        """A URL-fetched source never has stored_file_bytes; the file route 404s."""
        author = _make_author(client, id_suffix=f"pdf_nofile_{_uid()}")
        register_resp = client.post(
            f"/rag/authors/{author['id']}/ingest-urls",
            json={"urls": [f"https://example.com/report-{_uid()}.html"], "source_type": "html"},
        )
        source_id = register_resp.json()["sources"][0]["id"]

        resp = client.get(f"/rag/sources/{source_id}/file")
        assert resp.status_code == 404

    def test_get_source_file_404_for_another_users_source(self, client):
        """Serving someone else's stored file 404s, same as every other per-source endpoint."""
        from app.models.rag import RagSource

        author = _make_author(client, id_suffix=f"pdf_other_{_uid()}")
        with TestingSessionLocal() as db:
            other_source = RagSource(
                user_id=999,
                author_id=author["id"],
                source_type="pdf",
                status="ingested",
                stored_file_bytes=b"%PDF-1.4\nnot yours",
                stored_file_content_type="application/pdf",
                stored_file_filename="not-yours.pdf",
            )
            db.add(other_source)
            db.commit()
            other_source_id = other_source.id

        resp = client.get(f"/rag/sources/{other_source_id}/file")
        assert resp.status_code == 404


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
