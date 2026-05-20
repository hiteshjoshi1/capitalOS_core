from __future__ import annotations

import os
import uuid
from datetime import date
from unittest.mock import MagicMock, patch

os.environ.setdefault("RAG_EMBEDDING_MOCK", "1")
os.environ.setdefault("AUTH_BYPASS_USER_ID", "1")

from app.models.rag import RagAuthor, RagDocument, RagSource
from app.rag.ingestion.parser import StructuredParseResult
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


def _document_text(document: RagDocument) -> str:
    ordered_chunks = sorted(document.chunks, key=lambda chunk: chunk.chunk_index)
    return "\n".join(chunk.text for chunk in ordered_chunks)


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
              <ul>
                <li>Focus on ROIC</li>
                <li>Reinvest with discipline</li>
              </ul>
              <h1>Temperament</h1>
              <p>Investors should welcome volatility when the underlying business quality remains intact.</p>
              <table>
                <tr><th>Metric</th><th>Value</th></tr>
                <tr><td>ROE</td><td>15%</td></tr>
              </table>
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
            document_text = _document_text(documents[0])
            assert "capital allocation remains disciplined" in document_text
            assert "underlying business quality remains intact" in document_text
            assert not hasattr(documents[0], "content_blocks_json")
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

            primary_text = _document_text(primary)
            companion_text = _document_text(companion)
            assert "Revisited" not in primary_text
            assert "patient capital" in primary_text
            assert "patient capital" not in companion_text
            assert "changed later" in companion_text

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
            assert "usable because it explains" in _document_text(documents[0])

            outcomes = {entry["key"]: entry for entry in job.stats_json["documents"]}
            assert job.stats_json["documents_created"] == 1
            assert job.stats_json["documents_rejected"] == 1
            assert outcomes["brief-note"]["status"] == "created"
            assert outcomes["shell-only"]["status"] == "rejected"
            assert outcomes["shell-only"]["failure_category"] == FAILURE_LOW_QUALITY_EXTRACTION
        finally:
            db.close()

    def test_reingesting_source_replaces_legacy_omnibus_document_set(self):
        db = TestingSessionLocal()
        try:
            author = _add_author(db, _uid("sleep"), "Nick Sleep")
            source = RagSource(
                user_id=1,
                author_id=author.id,
                url="https://example.com/nomad-letters",
                source_type="html",
                status="pending",
            )
            db.add(source)
            db.flush()

            legacy_html = """
            <html><body>
              <h1>Full Collection of Nomad Letters</h1>
              <p>This omnibus edition combines many years of letters into a single giant work and should be replaced on reingestion.</p>
              <p>It also contains enough extra body text to pass validation as a single document before remediation happens.</p>
            </body></html>
            """

            with patch("app.rag.ingestion.pipeline.fetch_url", return_value=_mock_fetch(legacy_html, sha256="legacy-blob")):
                first_job = run_url_ingestion(source, db)
                db.commit()

            legacy_documents = db.query(RagDocument).filter(RagDocument.source_id == source.id).all()
            assert first_job.status == "done"
            assert len(legacy_documents) == 1
            assert "single giant work" in _document_text(legacy_documents[0])

            source.ingestion_config = {
                "mode": "fanout",
                "documents": [
                    {
                        "key": "letter-2008",
                        "title": "Nomad Letter 2008",
                        "author_id": author.id,
                        "published_at": "2008-06-30",
                        "publication_year": 2008,
                        "collection": "Nomad Letters",
                        "canonical_work_id": "letter-2008",
                        "canonical_status": "canonical",
                        "source_section": "June 30th, 2008",
                        "work_type": "letter",
                        "selective_options": {"include_headings": ["June 30th, 2008"]},
                    },
                    {
                        "key": "letter-2009",
                        "title": "Nomad Letter 2009",
                        "author_id": author.id,
                        "published_at": "2009-06-30",
                        "publication_year": 2009,
                        "collection": "Nomad Letters",
                        "canonical_work_id": "letter-2009",
                        "canonical_status": "canonical",
                        "source_section": "June 30th, 2009",
                        "work_type": "letter",
                        "selective_options": {"include_headings": ["June 30th, 2009"]},
                    },
                ],
            }

            fanout_html = """
            <html><body>
              <h1>June 30th, 2008</h1>
              <p>The 2008 letter explains why scale economies shared can create a durable edge when savings are handed back to customers.</p>
              <p>It also discusses patience, customer trust, and long holding periods with enough real body text for validation.</p>
              <h1>June 30th, 2009</h1>
              <p>The 2009 letter continues the same ideas with more discussion of Amazon, Costco, and long-term owner behavior.</p>
              <p>This section is likewise substantial and should become its own logical document after reingestion.</p>
            </body></html>
            """

            with patch("app.rag.ingestion.pipeline.fetch_url", return_value=_mock_fetch(fanout_html, sha256="letter-split")):
                second_job = run_url_ingestion(source, db)
                db.commit()

            documents = (
                db.query(RagDocument)
                .filter(RagDocument.source_id == source.id)
                .order_by(RagDocument.source_document_index.asc())
                .all()
            )

            assert second_job.status == "done"
            assert second_job.stats_json["ingestion_mode"] == "fanout"
            assert second_job.stats_json["documents_created"] == 2
            artifacts = {entry["key"]: entry for entry in second_job.stats_json["validation_artifacts"]}
            assert artifacts["letter-2008"]["status"] == "accepted"
            assert artifacts["letter-2008"]["author_id"] == author.id
            assert artifacts["letter-2008"]["quality"]["body_word_count"] >= 8
            assert artifacts["letter-2009"]["status"] == "accepted"
            assert artifacts["letter-2009"]["quality"]["body_word_count"] >= 8
            assert len(documents) == 2
            assert [document.title for document in documents] == ["Nomad Letter 2008", "Nomad Letter 2009"]
            assert all(document.author_id == author.id for document in documents)
            assert not any("single giant work" in _document_text(document) for document in documents)
        finally:
            db.close()

    def test_single_work_reingestion_preserves_existing_document_identity(self):
        db = TestingSessionLocal()
        try:
            author = _add_author(db, _uid("buffett"), "Warren Buffett")
            source = RagSource(
                user_id=1,
                author_id=author.id,
                url="https://example.com/buffett-2005.pdf",
                source_type="pdf",
                status="ingested",
            )
            db.add(source)
            db.flush()

            legacy = RagDocument(
                source_id=source.id,
                author_id=author.id,
                source_document_index=0,
                title="Berkshire Hathaway Shareholder Letter 2005",
                published_at=date(2005, 12, 31),
                publication_year=2005,
                venue="Berkshire Hathaway",
                collection="Shareholder Letters",
                canonical_work_id="buffett-2005",
                canonical_status="canonical",
                dedupe_priority=100,
                source_section="2005 Letter",
                work_type="letter",
                metadata_json={
                    "corpus_section": "Letters",
                    "source_label": "Canonical Buffett PDF",
                    "char_count": len("legacy clean text"),
                },
            )
            db.add(legacy)
            db.flush()

            parsed = StructuredParseResult(
                raw_text="BERKSHIRE HATHAWAY INC\nCorporate Performance vs. the S&P 500",
                clean_text="BERKSHIRE HATHAWAY INC\nCorporate Performance vs. the S&P 500",
                source_type="pdf",
                sections=[],
                doc_metadata={"title": "BERKSHIRE HATHAWAY INC"},
            )

            with patch("app.rag.ingestion.pipeline.fetch_url", return_value=MagicMock(raw_bytes=b"%PDF-1.4", sha256="buffett-2005", content_type="application/pdf")):
                with patch("app.rag.ingestion.pipeline.parse", return_value=parsed):
                    job = run_url_ingestion(source, db)
                    db.commit()

            documents = db.query(RagDocument).filter(RagDocument.source_id == source.id).all()
            assert job.status == "done"
            assert len(documents) == 1
            document = documents[0]
            assert document.title == "Berkshire Hathaway Shareholder Letter 2005"
            assert document.published_at == date(2005, 12, 31)
            assert document.publication_year == 2005
            assert document.venue == "Berkshire Hathaway"
            assert document.collection == "Shareholder Letters"
            assert document.canonical_work_id == "buffett-2005"
            assert document.canonical_status == "canonical"
            assert document.dedupe_priority == 100
            assert document.source_section == "2005 Letter"
            assert document.work_type == "letter"
            assert document.metadata_json["corpus_section"] == "Letters"
            assert document.metadata_json["source_label"] == "Canonical Buffett PDF"
        finally:
            db.close()

    def test_figure_blocks_and_modality_metadata_persist_through_ingestion(self):
        db = TestingSessionLocal()
        try:
            author = _add_author(db, _uid("figure"), "Figure Author")
            source = RagSource(
                user_id=1,
                author_id=author.id,
                url="https://example.com/figure-note",
                source_type="html",
                status="pending",
            )
            db.add(source)
            db.flush()

            html = """
            <html><body>
              <h1>Portfolio Review</h1>
              <figure>
                <img src="/figures/returns.png" alt="Five year total return chart" />
                <figcaption>Total return compared with the benchmark.</figcaption>
              </figure>
              <p>The chart shows a widening performance gap after 2021.</p>
              <ul>
                <li>Hold quality compounders</li>
                <li>Trim cyclicals</li>
              </ul>
            </body></html>
            """

            with patch("app.rag.ingestion.pipeline.fetch_url", return_value=_mock_fetch(html, sha256="figure-1")):
                job = run_url_ingestion(source, db)
                db.commit()

            document = db.query(RagDocument).filter(RagDocument.source_id == source.id).one()
            ordered_chunks = sorted(document.chunks, key=lambda chunk: chunk.chunk_index)

            assert job.status == "done"
            assert document.metadata_json["content_modalities"] == ["figure", "list", "prose"]
            figure_block = next(
                block for block in document.metadata_json["content_blocks"] if block["content_type"] == "figure"
            )
            assert figure_block["caption"] == "Total return compared with the benchmark."
            assert figure_block["explanatory_text"] == "The chart shows a widening performance gap after 2021."
            assert figure_block["modality"] == "figure"
            assert figure_block["section_path"] == ["Portfolio Review"]
            assert figure_block["source_ref"].startswith("html:block:")

            figure_chunk = next(chunk for chunk in ordered_chunks if chunk.metadata_json.get("modality") == "figure")
            assert figure_chunk.metadata_json["section_path"] == ["Portfolio Review"]
            assert figure_chunk.metadata_json["source_ref"] == figure_block["source_ref"]
            assert figure_chunk.metadata_json["caption"] == "Total return compared with the benchmark."
            assert figure_chunk.metadata_json["explanatory_text"] == (
                "The chart shows a widening performance gap after 2021."
            )

            list_chunk = next(chunk for chunk in ordered_chunks if chunk.metadata_json.get("modality") == "list")
            assert list_chunk.metadata_json["is_list"] is True
            assert list_chunk.metadata_json["section_path"] == ["Portfolio Review"]
        finally:
            db.close()

    def test_fanout_can_split_flat_pdf_text_with_source_level_markers(self):
        db = TestingSessionLocal()
        try:
            author = _add_author(db, _uid("nick"), "Nick Sleep")
            source = RagSource(
                user_id=1,
                author_id=author.id,
                url="https://example.com/nomad_letters.pdf",
                source_type="pdf",
                status="pending",
                ingestion_config={
                    "mode": "fanout",
                    "split_markers": [
                        {"marker": "18th January 2002", "heading": "18th January 2002"},
                        {"marker": "June 30th, 2002", "heading": "June 30th, 2002"},
                        {"marker": "Postamble", "heading": "Postamble"},
                    ],
                    "documents": [
                        {
                            "key": "nomad-letter-2002-01-18",
                            "title": "Nomad Investment Partnership Letter — 18 January 2002",
                            "author_id": author.id,
                            "published_at": "2002-01-18",
                            "publication_year": 2002,
                            "collection": "Nomad Investment Partnership Letters",
                            "canonical_work_id": "nomad-letter-2002-01-18",
                            "canonical_status": "canonical",
                            "source_section": "18th January 2002",
                            "work_type": "letter",
                            "selective_options": {"include_headings": ["18th January 2002"]},
                        },
                        {
                            "key": "nomad-letter-2002-06-30",
                            "title": "Nomad Investment Partnership Interim Report — June 2002",
                            "author_id": author.id,
                            "published_at": "2002-06-30",
                            "publication_year": 2002,
                            "collection": "Nomad Investment Partnership Letters",
                            "canonical_work_id": "nomad-letter-2002-06-30",
                            "canonical_status": "canonical",
                            "source_section": "For the period ended June 30th, 2002",
                            "work_type": "letter",
                            "selective_options": {"include_headings": ["June 30th, 2002"]},
                        },
                    ],
                },
            )
            db.add(source)
            db.flush()

            parsed = StructuredParseResult(
                raw_text=(
                    "Preamble\nSkip this opening material.\n\n"
                    "18th January 2002\n"
                    "To the Partners of the Nomad Investment Partnership.\n"
                    "The inaugural annual letter explains the fund launch, early holdings, and long-term orientation.\n\n"
                    "June 30th, 2002\n"
                    "Interim Report\n"
                    "This interim report discusses performance, Buffett partnership letters, and compressed time horizons.\n\n"
                    "Postamble\n"
                    "Skip this ending material.\n"
                ),
                clean_text=(
                    "Preamble\nSkip this opening material.\n\n"
                    "18th January 2002\n"
                    "To the Partners of the Nomad Investment Partnership.\n"
                    "The inaugural annual letter explains the fund launch, early holdings, and long-term orientation.\n\n"
                    "June 30th, 2002\n"
                    "Interim Report\n"
                    "This interim report discusses performance, Buffett partnership letters, and compressed time horizons.\n\n"
                    "Postamble\n"
                    "Skip this ending material.\n"
                ),
                source_type="pdf",
                sections=[],
                doc_metadata={},
            )

            with patch("app.rag.ingestion.pipeline.fetch_url", return_value=MagicMock(raw_bytes=b"%PDF-1.4", sha256="nick-flat", content_type="application/pdf")):
                with patch("app.rag.ingestion.pipeline.parse", return_value=parsed):
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
            assert job.stats_json["documents_created"] == 2
            assert [document.title for document in documents] == [
                "Nomad Investment Partnership Letter — 18 January 2002",
                "Nomad Investment Partnership Interim Report — June 2002",
            ]
            first_text = _document_text(documents[0])
            second_text = _document_text(documents[1])
            assert "Skip this opening material" not in first_text
            assert "Skip this ending material" not in second_text
            assert "To the Partners of the Nomad Investment Partnership." in first_text
            assert "Interim Report" in second_text
        finally:
            db.close()
