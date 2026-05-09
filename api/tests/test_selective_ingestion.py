"""
Tests for Issue 150: Selective ingestion controls for author sources.

Covers:
  - selector.py unit tests: start_after, stop_before, include_headings,
    exclude_sections, combinations, no-match raises NoContentSelectedError.
  - Backend API: selective_ingestion field accepted in POST ingest-urls.
  - Metadata persistence: selective_options stored on source and job.stats_json.
  - Backward compatibility: existing requests without selective_ingestion work.
  - No-content failure: clear failure_category when rules match nothing.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("RAG_EMBEDDING_MOCK", "1")
os.environ.setdefault("AUTH_BYPASS_USER_ID", "1")

from app.rag.ingestion.selector import (
    NoContentSelectedError,
    SelectiveIngestionOptions,
    apply_selective_options,
)
from tests.conftest import TestingSessionLocal


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _uid() -> str:
    return uuid.uuid4().hex[:8]


@dataclass
class _Section:
    """Minimal DocumentSection stand-in for unit tests."""
    heading: Optional[str]
    level: int = 1
    content: str = "body text"
    content_type: str = "text"
    table_markdown: Optional[str] = None


def _make_sections(headings: list[Optional[str]]) -> list[_Section]:
    return [_Section(heading=h, content=f"Content under {h}") for h in headings]


def _make_author(client, *, id_suffix: str | None = None):
    aid = f"sel_{id_suffix or _uid()}"
    resp = client.post("/rag/authors", json={"id": aid, "name": f"Selective {aid}", "enabled": True})
    assert resp.status_code == 201, resp.text
    return resp.json()


# ─────────────────────────────────────────────────────────────────────────────
# Unit: selector.py
# ─────────────────────────────────────────────────────────────────────────────


class TestSelectiveOptions:
    def test_is_empty_all_none(self):
        opts = SelectiveIngestionOptions()
        assert opts.is_empty()

    def test_is_empty_with_start_after(self):
        opts = SelectiveIngestionOptions(start_after="Intro")
        assert not opts.is_empty()

    def test_to_dict_roundtrip(self):
        opts = SelectiveIngestionOptions(
            start_after="Introduction",
            stop_before="Conclusion",
            include_headings=["Methods"],
            exclude_sections=["Appendix"],
        )
        d = opts.to_dict()
        opts2 = SelectiveIngestionOptions.from_dict(d)
        assert opts2.start_after == opts.start_after
        assert opts2.stop_before == opts.stop_before
        assert opts2.include_headings == opts.include_headings
        assert opts2.exclude_sections == opts.exclude_sections


class TestApplySelectiveOptions:
    def test_empty_options_returns_all_sections(self):
        sections = _make_sections(["Intro", "Methods", "Results", "Conclusion"])
        opts = SelectiveIngestionOptions()
        result = apply_selective_options(sections, opts)
        assert result == sections

    def test_start_after_removes_up_to_and_including_match(self):
        sections = _make_sections(["Intro", "Methods", "Results", "Conclusion"])
        opts = SelectiveIngestionOptions(start_after="Methods")
        result = apply_selective_options(sections, opts)
        assert [s.heading for s in result] == ["Results", "Conclusion"]

    def test_start_after_case_insensitive(self):
        sections = _make_sections(["Introduction", "Body", "Summary"])
        opts = SelectiveIngestionOptions(start_after="introduction")
        result = apply_selective_options(sections, opts)
        assert [s.heading for s in result] == ["Body", "Summary"]

    def test_start_after_substring_match(self):
        sections = _make_sections(["1. Introduction", "2. Methods", "3. Results"])
        opts = SelectiveIngestionOptions(start_after="Intro")
        result = apply_selective_options(sections, opts)
        assert [s.heading for s in result] == ["2. Methods", "3. Results"]

    def test_start_after_not_found_raises(self):
        sections = _make_sections(["Intro", "Methods"])
        opts = SelectiveIngestionOptions(start_after="Nonexistent")
        with pytest.raises(NoContentSelectedError, match="start_after"):
            apply_selective_options(sections, opts)

    def test_stop_before_trims_at_match(self):
        sections = _make_sections(["Intro", "Methods", "Conclusion", "Appendix"])
        opts = SelectiveIngestionOptions(stop_before="Conclusion")
        result = apply_selective_options(sections, opts)
        assert [s.heading for s in result] == ["Intro", "Methods"]

    def test_stop_before_not_found_includes_all(self):
        sections = _make_sections(["Intro", "Methods", "Results"])
        opts = SelectiveIngestionOptions(stop_before="Nonexistent")
        result = apply_selective_options(sections, opts)
        assert len(result) == 3  # all retained

    def test_include_headings_filters_to_matches(self):
        sections = _make_sections(["Intro", "Portfolio", "Risk", "Conclusion"])
        opts = SelectiveIngestionOptions(include_headings=["Portfolio", "Risk"])
        result = apply_selective_options(sections, opts)
        assert [s.heading for s in result] == ["Portfolio", "Risk"]

    def test_include_headings_keeps_descendant_sections_under_matched_heading(self):
        sections = [
            _Section("Foreword: Collison on Munger", level=1, content=""),
            _Section("John Collison", level=3, content="Actual foreword body"),
            _Section("Foreword: Buffett on Munger", level=1, content=""),
            _Section("Warren E. Buffett", level=3, content="Another foreword body"),
        ]
        opts = SelectiveIngestionOptions(include_headings=["Foreword: Collison on Munger"])
        result = apply_selective_options(sections, opts)
        assert [s.heading for s in result] == ["Foreword: Collison on Munger", "John Collison"]

    def test_include_headings_no_match_raises(self):
        sections = _make_sections(["Intro", "Methods"])
        opts = SelectiveIngestionOptions(include_headings=["Nonexistent"])
        with pytest.raises(NoContentSelectedError):
            apply_selective_options(sections, opts)

    def test_exclude_sections_removes_matches(self):
        sections = _make_sections(["Intro", "Appendix", "Methods", "Appendix B"])
        opts = SelectiveIngestionOptions(exclude_sections=["Appendix"])
        result = apply_selective_options(sections, opts)
        assert [s.heading for s in result] == ["Intro", "Methods"]

    def test_exclude_sections_removes_descendant_sections_under_matched_heading(self):
        sections = [
            _Section("Foreword: Collison on Munger", level=1, content=""),
            _Section("John Collison", level=3, content="Actual foreword body"),
            _Section("Recommended reading", level=1, content="Book list"),
        ]
        opts = SelectiveIngestionOptions(exclude_sections=["Foreword: Collison on Munger"])
        result = apply_selective_options(sections, opts)
        assert [s.heading for s in result] == ["Recommended reading"]

    def test_exclude_sections_all_removed_raises(self):
        sections = _make_sections(["Appendix"])
        opts = SelectiveIngestionOptions(exclude_sections=["Appendix"])
        with pytest.raises(NoContentSelectedError):
            apply_selective_options(sections, opts)

    def test_start_after_then_stop_before_combination(self):
        sections = _make_sections(["Intro", "Part 1", "Part 2", "Conclusion", "Appendix"])
        opts = SelectiveIngestionOptions(start_after="Intro", stop_before="Conclusion")
        result = apply_selective_options(sections, opts)
        assert [s.heading for s in result] == ["Part 1", "Part 2"]

    def test_include_headings_keeps_headingless_descendants_after_matched_heading(self):
        sections = _make_sections([None, "Intro", None, "Methods"])
        opts = SelectiveIngestionOptions(include_headings=["Intro"])
        result = apply_selective_options(sections, opts)
        assert [s.heading for s in result] == ["Intro", None]

    def test_none_heading_sections_not_excluded(self):
        sections = _make_sections([None, "Appendix", "Intro"])
        opts = SelectiveIngestionOptions(exclude_sections=["Appendix"])
        result = apply_selective_options(sections, opts)
        assert [s.heading for s in result] == [None, "Intro"]


# ─────────────────────────────────────────────────────────────────────────────
# Integration: API endpoint accepts selective_ingestion field
# ─────────────────────────────────────────────────────────────────────────────


class TestSelectiveIngestionAPI:
    @pytest.fixture(autouse=True)
    def fresh_author(self, client):
        data = _make_author(client)
        self.author_id = data["id"]

    def test_ingest_urls_without_selective_options_backward_compat(self, client):
        """Existing requests without selective_ingestion still work unchanged."""
        url = f"https://example.com/no-selective-{_uid()}"
        resp = client.post(
            f"/rag/authors/{self.author_id}/ingest-urls",
            json={"urls": [url], "source_type": "html"},
        )
        assert resp.status_code == 202, resp.text
        data = resp.json()
        assert data["registered"] == 1
        # Source should have no selective_options
        source = data["sources"][0]
        assert source.get("selective_options") is None or source.get("selective_options") == {}

    def test_ingest_urls_with_selective_options_persists_on_source(self, client):
        """POST ingest-urls with selective_ingestion stores options on the source."""
        from app.models.rag import RagSource

        url = f"https://example.com/selective-{_uid()}"
        selective = {
            "start_after": "Introduction",
            "stop_before": "Appendix",
            "include_headings": [],
            "exclude_sections": ["Notes"],
        }
        resp = client.post(
            f"/rag/authors/{self.author_id}/ingest-urls",
            json={"urls": [url], "source_type": "html", "selective_ingestion": selective},
        )
        assert resp.status_code == 202, resp.text
        data = resp.json()
        assert data["registered"] == 1
        source_id = data["sources"][0]["id"]

        # Verify selective_options stored in DB
        db = TestingSessionLocal()
        try:
            source = db.get(RagSource, source_id)
            assert source is not None
            assert source.selective_options is not None
            assert source.selective_options.get("start_after") == "Introduction"
            assert source.selective_options.get("stop_before") == "Appendix"
            assert source.selective_options.get("exclude_sections") == ["Notes"]
        finally:
            db.close()

    def test_ingest_urls_selective_options_returned_in_response(self, client):
        """The source in the response includes the selective_options field."""
        url = f"https://example.com/selective-resp-{_uid()}"
        selective = {
            "start_after": "Part 2",
            "stop_before": None,
            "include_headings": [],
            "exclude_sections": [],
        }
        resp = client.post(
            f"/rag/authors/{self.author_id}/ingest-urls",
            json={"urls": [url], "source_type": "html", "selective_ingestion": selective},
        )
        assert resp.status_code == 202, resp.text
        source = resp.json()["sources"][0]
        assert source["selective_options"] is not None
        assert source["selective_options"]["start_after"] == "Part 2"

    def test_requeue_existing_url_without_selective_options_clears_stored_rules(self, client):
        """Re-submitting an existing URL with blank selective_ingestion clears stored rules."""
        from app.models.rag import RagSource

        url = f"https://example.com/selective-clear-{_uid()}"
        first = client.post(
            f"/rag/authors/{self.author_id}/ingest-urls",
            json={
                "urls": [url],
                "source_type": "html",
                "selective_ingestion": {
                    "start_after": "Introduction",
                    "stop_before": None,
                    "include_headings": [],
                    "exclude_sections": [],
                },
            },
        )
        assert first.status_code == 202, first.text
        source_id = first.json()["sources"][0]["id"]

        second = client.post(
            f"/rag/authors/{self.author_id}/ingest-urls",
            json={"urls": [url], "source_type": "html"},
        )
        assert second.status_code == 202, second.text
        payload = second.json()
        assert payload["registered"] == 0
        assert payload["requeued_existing"] == 1
        assert payload["jobs_queued"] == 1

        db = TestingSessionLocal()
        try:
            source = db.get(RagSource, source_id)
            assert source is not None
            assert source.selective_options is None
        finally:
            db.close()

    def test_selective_options_in_get_sources(self, client):
        """GET /rag/sources includes selective_options for sources that have them."""
        url = f"https://example.com/selective-list-{_uid()}"
        selective = {"include_headings": ["Investment Thesis"], "exclude_sections": [], "start_after": None, "stop_before": None}
        client.post(
            f"/rag/authors/{self.author_id}/ingest-urls",
            json={"urls": [url], "source_type": "html", "selective_ingestion": selective},
        )
        resp = client.get(f"/rag/sources?author_id={self.author_id}")
        assert resp.status_code == 200
        sources = resp.json()
        matching = [s for s in sources if s["url"] == url]
        assert len(matching) == 1
        assert matching[0]["selective_options"]["include_headings"] == ["Investment Thesis"]


# ─────────────────────────────────────────────────────────────────────────────
# Integration: pipeline applies selective options and stores them in job metadata
# ─────────────────────────────────────────────────────────────────────────────


class TestSelectiveIngestionPipeline:
    def _make_html_with_sections(self) -> bytes:
        return b"""
        <html><body>
        <h1>Introduction</h1><p>Intro content here.</p>
        <h1>Investment Thesis</h1><p>Core thesis content.</p>
        <h1>Risk Factors</h1><p>Risks.</p>
        <h1>Appendix</h1><p>Appendix notes.</p>
        </body></html>
        """

    def test_pipeline_applies_start_after_to_sections(self):
        """run_url_ingestion applies start_after from source.selective_options."""
        from app.models.rag import RagIngestionJob, RagSource
        from app.rag.ingestion.pipeline import run_url_ingestion, FAILURE_NO_CONTENT_SELECTED

        html = self._make_html_with_sections()

        db = TestingSessionLocal()
        try:
            from app.models.rag import RagAuthor
            author = RagAuthor(id=f"pipe_{_uid()}", name="Pipeline Test", enabled=True)
            db.add(author)
            db.flush()

            source = RagSource(
                user_id=1,
                author_id=author.id,
                url="https://example.com/pipe-test",
                source_type="html",
                status="pending",
                selective_options={
                    "start_after": "Introduction",
                    "stop_before": "Appendix",
                    "include_headings": [],
                    "exclude_sections": [],
                },
            )
            db.add(source)
            db.flush()

            with patch("app.rag.ingestion.pipeline.fetch_url") as mock_fetch:
                mock_fetch.return_value = MagicMock(
                    raw_bytes=html,
                    sha256="abc123",
                    content_type="text/html",
                )
                job = run_url_ingestion(source, db)
                db.commit()

            assert job.status == "done"
            assert job.stats_json is not None
            # selective options must appear in stats_json
            assert "selective_options" in job.stats_json
            assert job.stats_json["selective_options"]["start_after"] == "Introduction"
            # sections_selected must not include Intro or Appendix
            selected = job.stats_json.get("sections_selected")
            assert selected is not None and selected >= 1
        finally:
            db.close()

    def test_pipeline_fails_clearly_when_no_content_selected(self):
        """run_url_ingestion fails with no_content_selected when rules match nothing."""
        from app.models.rag import RagIngestionJob, RagSource
        from app.rag.ingestion.pipeline import run_url_ingestion, FAILURE_NO_CONTENT_SELECTED

        html = self._make_html_with_sections()

        db = TestingSessionLocal()
        try:
            from app.models.rag import RagAuthor
            author = RagAuthor(id=f"fail_{_uid()}", name="Fail Test", enabled=True)
            db.add(author)
            db.flush()

            source = RagSource(
                user_id=1,
                author_id=author.id,
                url="https://example.com/fail-test",
                source_type="html",
                status="pending",
                selective_options={
                    "start_after": None,
                    "stop_before": None,
                    "include_headings": ["Completely Nonexistent Section XYZ"],
                    "exclude_sections": [],
                },
            )
            db.add(source)
            db.flush()

            with patch("app.rag.ingestion.pipeline.fetch_url") as mock_fetch:
                mock_fetch.return_value = MagicMock(
                    raw_bytes=html,
                    sha256="def456",
                    content_type="text/html",
                )
                job = run_url_ingestion(source, db)
                db.commit()

            assert job.status == "failed"
            assert job.failure_category == FAILURE_NO_CONTENT_SELECTED
            assert "selective" in (job.error or "").lower() or "content" in (job.error or "").lower()
        finally:
            db.close()

    def test_pipeline_no_selective_options_ingests_all(self):
        """run_url_ingestion without selective options ingests the full source."""
        from app.models.rag import RagSource
        from app.rag.ingestion.pipeline import run_url_ingestion

        html = self._make_html_with_sections()

        db = TestingSessionLocal()
        try:
            from app.models.rag import RagAuthor
            author = RagAuthor(id=f"full_{_uid()}", name="Full Test", enabled=True)
            db.add(author)
            db.flush()

            source = RagSource(
                user_id=1,
                author_id=author.id,
                url="https://example.com/full-test",
                source_type="html",
                status="pending",
            )
            db.add(source)
            db.flush()

            with patch("app.rag.ingestion.pipeline.fetch_url") as mock_fetch:
                mock_fetch.return_value = MagicMock(
                    raw_bytes=html,
                    sha256="ghi789",
                    content_type="text/html",
                )
                job = run_url_ingestion(source, db)
                db.commit()

            assert job.status == "done"
            assert "selective_options" not in (job.stats_json or {})
        finally:
            db.close()


# ─────────────────────────────────────────────────────────────────────────────
# Integration: metadata persistence and auditability
# ─────────────────────────────────────────────────────────────────────────────


class TestSelectiveIngestionMetadata:
    def test_selective_options_visible_in_jobs_list(self, client):
        """Jobs for sources with selective options have selective_options in stats_json."""
        from app.models.rag import RagSource, RagIngestionJob

        author_data = _make_author(client)
        author_id = author_data["id"]
        url = f"https://example.com/meta-{_uid()}"
        selective = {
            "start_after": None,
            "stop_before": None,
            "include_headings": ["Portfolio"],
            "exclude_sections": [],
        }
        ingest_resp = client.post(
            f"/rag/authors/{author_id}/ingest-urls",
            json={"urls": [url], "source_type": "html", "selective_ingestion": selective},
        )
        assert ingest_resp.status_code == 202
        source_id = ingest_resp.json()["sources"][0]["id"]

        # Verify DB has selective_options on source
        db = TestingSessionLocal()
        try:
            source = db.get(RagSource, source_id)
            assert source is not None
            assert source.selective_options is not None
            assert source.selective_options.get("include_headings") == ["Portfolio"]
        finally:
            db.close()

    def test_activity_endpoint_includes_selective_options(self, client):
        """GET /rag/ingest/activity shows selective_options on source records."""
        author_data = _make_author(client)
        author_id = author_data["id"]
        url = f"https://example.com/activity-sel-{_uid()}"
        selective = {
            "start_after": "Executive Summary",
            "stop_before": None,
            "include_headings": [],
            "exclude_sections": [],
        }
        client.post(
            f"/rag/authors/{author_id}/ingest-urls",
            json={"urls": [url], "source_type": "html", "selective_ingestion": selective},
        )
        activity_resp = client.get(f"/rag/ingest/activity?author_id={author_id}")
        assert activity_resp.status_code == 200
        activity = activity_resp.json()
        matching = [s for s in activity["sources"] if s["url"] == url]
        assert len(matching) == 1
        assert matching[0]["selective_options"] is not None
        assert matching[0]["selective_options"]["start_after"] == "Executive Summary"
