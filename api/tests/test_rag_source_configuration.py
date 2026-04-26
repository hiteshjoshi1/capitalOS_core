from __future__ import annotations

import os
import uuid
from unittest.mock import MagicMock, patch

os.environ.setdefault("RAG_EMBEDDING_MOCK", "1")
os.environ.setdefault("AUTH_BYPASS_USER_ID", "1")

from app.models.rag import RagAuthor, RagDocument, RagSource
from app.rag.discovery import DiscoveredSource, _register_sources
from app.rag.ingestion.normalization import apply_section_splits
from app.rag.ingestion.parser import DocumentSection
from app.rag.ingestion.source_presets import apply_source_preset
from tests.conftest import TestingSessionLocal


def _upsert_author(db, author_id: str, name: str) -> None:
    if db.get(RagAuthor, author_id) is not None:
        return
    db.add(RagAuthor(id=author_id, name=name, enabled=True))
    db.flush()


def test_apply_source_preset_is_passthrough():
    ingestion_config = {"mode": "fanout", "documents": [{"key": "doc-1", "title": "Doc 1"}]}
    selective_options = {"start_after": "Section A", "stop_before": "Section B"}

    effective_config, effective_options = apply_source_preset(
        author_id="charlie_munger",
        url="https://www.stripe.press/poor-charlies-almanack/book?progress=0.00%25",
        ingestion_config=ingestion_config,
        selective_options=selective_options,
    )

    assert effective_config == ingestion_config
    assert effective_options == selective_options
    assert effective_config is not ingestion_config
    assert effective_options is not selective_options


def test_discovery_registers_sources_without_inferred_ingestion_config():
    db = TestingSessionLocal()
    try:
        _upsert_author(db, "charlie_munger", "Charlie Munger")
        sources = [
            DiscoveredSource(
                url="https://www.stripe.press/poor-charlies-almanack/book?progress=0.00%25",
                source_type="html",
            ),
            DiscoveredSource(
                url="https://worldlypartners.com/wp-content/uploads/2024/01/2020-charlie-munger-at-caltech.pdf",
                source_type="pdf",
            ),
        ]

        registered, skipped = _register_sources("charlie_munger", sources, set(), db)
        db.commit()

        assert registered == 2
        assert skipped == 0

        rows = {
            row.url: row for row in db.query(RagSource).filter(RagSource.author_id == "charlie_munger").all()
        }
        assert rows[sources[0].url].ingestion_config is None
        assert rows[sources[0].url].selective_options is None
        assert rows[sources[1].url].ingestion_config is None
        assert rows[sources[1].url].selective_options is None
    finally:
        db.close()


def test_apply_section_splits_is_generic_and_source_agnostic():
    sections = [
        DocumentSection(
            heading="Composite Section",
            level=3,
            content=(
                "Intro body.\n"
                "Marker A\n"
                "Body A.\n"
                "Marker B\n"
                "Body B."
            ),
            content_type="text",
        )
    ]

    split_sections = apply_section_splits(
        sections,
        [
            {
                "match_heading": "Composite Section",
                "markers": [
                    {"marker": "Marker A", "heading": "Section A", "level": 4},
                    {"marker": "Marker B", "heading": "Section B", "level": 4},
                ],
            }
        ],
    )

    assert [section.heading for section in split_sections] == [
        "Composite Section",
        "Section A",
        "Section B",
    ]
    assert split_sections[0].content.strip() == "Intro body."
    assert split_sections[1].content.strip() == "Body A."
    assert split_sections[2].content.strip() == "Body B."


def test_validate_endpoint_uses_explicit_ingestion_config_without_persisting_documents(client):
    db = TestingSessionLocal()
    try:
        author_id = f"author_{uuid.uuid4().hex[:8]}"
        supporting_author_id = f"author_{uuid.uuid4().hex[:8]}"
        _upsert_author(db, author_id, "Primary Author")
        _upsert_author(db, supporting_author_id, "Supporting Author")
        source = RagSource(
            user_id=1,
            author_id=author_id,
            url="https://example.com/omnibus",
            source_type="html",
            status="pending",
            ingestion_config={
                "mode": "fanout",
                "documents": [
                        {
                            "key": "doc-one",
                            "title": "Document One",
                            "canonical_work_id": "doc_one",
                            "source_section": "Doc One -> before Doc Two",
                            "selective_options": {
                                "include_headings": ["Doc One"],
                            },
                        },
                        {
                            "key": "doc-two",
                            "title": "Document Two",
                            "author_id": supporting_author_id,
                            "canonical_work_id": "doc_two",
                            "source_section": "Doc Two -> before References",
                            "selective_options": {
                                "include_headings": ["Doc Two"],
                            },
                        },
                ],
            },
        )
        db.add(source)
        db.commit()
        db.refresh(source)

        doc_one_body = (
            "Document one has enough body text to validate cleanly and should stop before the next heading. "
            "It includes several full sentences about incentives, mental models, capital allocation, and decision quality "
            "so the deterministic validator sees real content instead of a heading stub. "
            "This paragraph intentionally adds length and substance to look like a legitimate extracted section."
        )
        doc_two_body = (
            "Document two also has enough real body text to become its own logical document. "
            "It discusses multidisciplinary reasoning, error avoidance, compounding, and practical judgment across "
            "business contexts, which makes it suitable for deterministic quality validation. "
            "This section is long enough that it should not be rejected as low-quality extraction."
        )

        html = f"""
        <html><body>
          <h2>Doc One</h2>
          <p>{doc_one_body}</p>
          <h2>Doc Two</h2>
          <p>{doc_two_body}</p>
          <h2>References</h2>
          <p>Reference material should not bleed into Document Two.</p>
        </body></html>
        """

        with patch(
            "app.rag.ingestion.pipeline.fetch_url",
            return_value=MagicMock(raw_bytes=html.encode("utf-8"), sha256="fixture", content_type="text/html"),
        ):
            resp = client.post("/rag/ingest/validate", json={"source_id": str(source.id)})

        assert resp.status_code == 200, resp.text
        body = resp.json()
        documents = {entry["key"]: entry for entry in body["documents"]}
        assert body["document_count"] == 2
        assert body["accepted_count"] == 2
        assert body["rejected_count"] == 0
        assert documents["doc-one"]["status"] == "accepted"
        assert documents["doc-one"]["source_section"] == "Doc One -> before Doc Two"
        assert documents["doc-two"]["status"] == "accepted"
        assert documents["doc-two"]["author_id"] == supporting_author_id
        assert documents["doc-two"]["included_sections"] == ["Doc Two"]

        stored_documents = db.query(RagDocument).filter(RagDocument.source_id == source.id).all()
        assert stored_documents == []
    finally:
        db.close()
