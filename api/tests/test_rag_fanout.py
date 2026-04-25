from __future__ import annotations

import os
import uuid
from unittest.mock import MagicMock, patch

os.environ.setdefault("RAG_EMBEDDING_MOCK", "1")
os.environ.setdefault("AUTH_BYPASS_USER_ID", "1")

from app.models.rag import RagAuthor, RagDocument, RagSource
from app.rag.ingestion.pipeline import (
    FAILURE_LOW_QUALITY_EXTRACTION,
    run_url_ingestion,
)
from tests.conftest import TestingSessionLocal


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _add_author(db, author_id: str, name: str) -> RagAuthor:
    author = RagAuthor(id=author_id, name=name, enabled=True)
    db.add(author)
    db.flush()
    return author


def _mock_fetch(raw_html: str, sha256: str = "fanout-sha") -> MagicMock:
    return MagicMock(raw_bytes=raw_html.encode("utf-8"), sha256=sha256, content_type="text/html")


class TestRagFanoutPipeline:
    def test_single_work_path_still_persists_one_document(self):
        db = TestingSessionLocal()
        try:
            author = _add_author(db, _uid("single"), "Single Work Author")
            source = RagSource(
                user_id=1,
                author_id=author.id,
                url="https://example.com/single-work",
                source_type="html",
                status="pending",
            )
            db.add(source)
            db.flush()

            html = """
            <html><body>
              <h1>Compounders</h1>
              <p>Great businesses can keep compounding for long periods when capital allocation remains disciplined.</p>
              <h1>Temperament</h1>
              <p>Investors should welcome volatility when the underlying business quality remains intact.</p>
            </body></html>
            """

            with patch("app.rag.ingestion.pipeline.fetch_url", return_value=_mock_fetch(html)):
                job = run_url_ingestion(source, db)
                db.commit()

            documents = db.query(RagDocument).filter(RagDocument.source_id == source.id).all()
            assert job.status == "done"
            assert job.stats_json["ingestion_mode"] == "single_work"
            assert len(documents) == 1
            assert documents[0].author_id == author.id
            assert "Compounders" in (source.clean_text or "")
            assert "Temperament" in (source.clean_text or "")
            assert "Compounders" in (documents[0].clean_text or "")
            assert "Temperament" in (documents[0].clean_text or "")
        finally:
            db.close()

    def test_fanout_persists_metadata_parent_child_and_author_override(self):
        db = TestingSessionLocal()
        try:
            source_author = _add_author(db, _uid("omnibus"), "Collected Talks Editor")
            talk_author = _add_author(db, _uid("speaker"), "Talk Speaker")
            editor_author = _add_author(db, _uid("editor"), "Editorial Team")
            source = RagSource(
                user_id=1,
                author_id=source_author.id,
                url="https://example.com/omnibus",
                source_type="html",
                status="pending",
                ingestion_config={
                    "mode": "fanout",
                    "documents": [
                        {
                            "key": "talk-x",
                            "title": "Talk X",
                            "author_id": talk_author.id,
                            "publication_year": 1998,
                            "venue": "Annual Meeting",
                            "collection": "Collected Talks",
                            "canonical_work_id": "talk-x",
                            "canonical_status": "canonical",
                            "dedupe_priority": 100,
                            "source_section": "Talk X",
                            "work_type": "talk",
                            "selective_options": {"include_headings": ["Talk X"], "stop_before": "Talk X Revisited"},
                        },
                        {
                            "key": "talk-x-revisited",
                            "title": "Talk X Revisited",
                            "author_id": editor_author.id,
                            "collection": "Collected Talks",
                            "source_section": "Talk X Revisited",
                            "note_taker": "Editorial Team",
                            "work_type": "editorial_companion",
                            "parent_key": "talk-x",
                            "selective_options": {"include_headings": ["Talk X Revisited"]},
                        },
                    ],
                },
            )
            db.add(source)
            db.flush()

            html = """
            <html><body>
              <h1>Front Matter</h1>
              <p>Collected talks for archive use.</p>
              <h1>Talk X</h1>
              <p>Talk X explains how patient capital and disciplined underwriting create durable compounding across cycles.</p>
              <h1>Talk X Revisited</h1>
              <p>The editorial revisit adds context on what changed later and which conclusions still held up over time.</p>
            </body></html>
            """

            with patch("app.rag.ingestion.pipeline.fetch_url", return_value=_mock_fetch(html, sha256="fanout-1")):
                job = run_url_ingestion(source, db)
                db.commit()

            documents = (
                db.query(RagDocument)
                .filter(RagDocument.source_id == source.id)
                .order_by(RagDocument.source_document_index.asc())
                .all()
            )

            assert job.status == "done"
            assert job.stats_json["ingestion_mode"] == "fanout"
            assert len(documents) == 2

            primary, companion = documents
            assert primary.author_id == talk_author.id
            assert primary.publication_year == 1998
            assert primary.venue == "Annual Meeting"
            assert primary.collection == "Collected Talks"
            assert primary.canonical_work_id == "talk-x"
            assert primary.canonical_status == "canonical"
            assert primary.dedupe_priority == 100
            assert primary.work_type == "talk"

            assert companion.author_id == editor_author.id
            assert companion.parent_document_id == primary.id
            assert companion.note_taker == "Editorial Team"
            assert companion.work_type == "editorial_companion"

            assert "Revisited" not in (primary.clean_text or "")
            assert "patient capital" in (primary.clean_text or "")
            assert "patient capital" not in (companion.clean_text or "")
            assert "changed later" in (companion.clean_text or "")
            assert "Talk X Revisited" in (source.clean_text or "")

            created = {entry["key"]: entry for entry in job.stats_json["documents"] if entry["status"] == "created"}
            assert created["talk-x"]["author_id"] == talk_author.id
            assert created["talk-x-revisited"]["author_id"] == editor_author.id
            assert created["talk-x-revisited"]["parent_document_id"] == str(primary.id)
        finally:
            db.close()

    def test_single_work_low_quality_shell_only_selection_fails(self):
        db = TestingSessionLocal()
        try:
            author = _add_author(db, _uid("thin"), "Thin Content Author")
            source = RagSource(
                user_id=1,
                author_id=author.id,
                url="https://example.com/thin",
                source_type="html",
                status="pending",
                selective_options={
                    "include_headings": ["Shell Only"],
                    "start_after": None,
                    "stop_before": None,
                    "exclude_sections": [],
                },
            )
            db.add(source)
            db.flush()

            html = """
            <html><body>
              <h1>Intro</h1>
              <p>Archive landing page.</p>
              <h1>Shell Only</h1>
              <p>Shell Only</p>
            </body></html>
            """

            with patch("app.rag.ingestion.pipeline.fetch_url", return_value=_mock_fetch(html, sha256="thin-1")):
                job = run_url_ingestion(source, db)
                db.commit()

            documents = db.query(RagDocument).filter(RagDocument.source_id == source.id).all()
            assert job.status == "failed"
            assert job.failure_category == FAILURE_LOW_QUALITY_EXTRACTION
            assert documents == []
            assert job.stats_json["documents_created"] == 0
            assert job.stats_json["documents"][0]["status"] == "rejected"
            assert job.stats_json["documents"][0]["failure_category"] == FAILURE_LOW_QUALITY_EXTRACTION
        finally:
            db.close()

    def test_fanout_accepts_valid_short_document_and_rejects_shell_only_companion(self):
        db = TestingSessionLocal()
        try:
            source_author = _add_author(db, _uid("bundle"), "Bundle Editor")
            brief_author = _add_author(db, _uid("brief"), "Brief Author")
            source = RagSource(
                user_id=1,
                author_id=source_author.id,
                url="https://example.com/brief-bundle",
                source_type="html",
                status="pending",
                ingestion_config={
                    "mode": "fanout",
                    "documents": [
                        {
                            "key": "brief-note",
                            "title": "Brief Note",
                            "author_id": brief_author.id,
                            "work_type": "note",
                            "selective_options": {"include_headings": ["Brief Note"]},
                        },
                        {
                            "key": "shell-only",
                            "title": "Shell Only",
                            "author_id": source_author.id,
                            "work_type": "note",
                            "selective_options": {"include_headings": ["Shell Only"]},
                        },
                    ],
                },
            )
            db.add(source)
            db.flush()

            html = """
            <html><body>
              <h1>Brief Note</h1>
              <p>This short note is complete, specific, and usable because it explains the key takeaway in one compact paragraph.</p>
              <h1>Shell Only</h1>
              <p>Shell Only</p>
            </body></html>
            """

            with patch("app.rag.ingestion.pipeline.fetch_url", return_value=_mock_fetch(html, sha256="brief-1")):
                job = run_url_ingestion(source, db)
                db.commit()

            documents = (
                db.query(RagDocument)
                .filter(RagDocument.source_id == source.id)
                .order_by(RagDocument.source_document_index.asc())
                .all()
            )
            assert job.status == "done"
            assert len(documents) == 1
            assert documents[0].title == "Brief Note"
            assert "usable because it explains" in (documents[0].clean_text or "")

            outcomes = {entry["key"]: entry for entry in job.stats_json["documents"]}
            assert job.stats_json["documents_created"] == 1
            assert job.stats_json["documents_rejected"] == 1
            assert outcomes["brief-note"]["status"] == "created"
            assert outcomes["shell-only"]["status"] == "rejected"
            assert outcomes["shell-only"]["failure_category"] == FAILURE_LOW_QUALITY_EXTRACTION
        finally:
            db.close()
