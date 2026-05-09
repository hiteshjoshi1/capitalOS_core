from __future__ import annotations

import os
import uuid
from unittest.mock import patch

os.environ.setdefault("RAG_EMBEDDING_MOCK", "1")
os.environ.setdefault("AUTH_BYPASS_USER_ID", "1")

from app.models.rag import RagAuthor, RagDocument, RagSource
from tests.conftest import TestingSessionLocal


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _add_author(
    db,
    author_id: str,
    name: str,
    *,
    role_type: str | None = None,
    domains: list[str] | None = None,
    expertise_tags: list[str] | None = None,
) -> RagAuthor:
    author = RagAuthor(
        id=author_id,
        name=name,
        enabled=True,
        role_type=role_type,
        domains=domains or [],
        expertise_tags=expertise_tags or [],
    )
    db.add(author)
    db.flush()
    return author


def _add_source(db, *, author_id: str, url: str, source_type: str = "html") -> RagSource:
    source = RagSource(
        user_id=1,
        author_id=author_id,
        url=url,
        source_type=source_type,
        status="ingested",
    )
    db.add(source)
    db.flush()
    return source


def _add_document(
    db,
    *,
    source_id: str,
    title: str,
    clean_text: str,
    content_blocks_json: list[dict] | None = None,
    author_id: str | None = None,
    publication_year: int | None = None,
    venue: str | None = None,
    collection: str | None = None,
    canonical_status: str | None = None,
    work_type: str | None = None,
    source_section: str | None = None,
    metadata_json: dict | None = None,
    parent_document_id: str | None = None,
    source_document_index: int = 0,
) -> RagDocument:
    document = RagDocument(
        source_id=source_id,
        author_id=author_id,
        parent_document_id=parent_document_id,
        source_document_index=source_document_index,
        title=title,
        publication_year=publication_year,
        venue=venue,
        collection=collection,
        canonical_status=canonical_status,
        work_type=work_type,
        source_section=source_section,
        metadata_json=metadata_json or {},
        raw_text=clean_text,
        clean_text=clean_text,
        content_blocks_json=content_blocks_json,
    )
    db.add(document)
    db.flush()
    return document


def test_library_lists_effective_authors_grouped_documents_and_fallbacks(client):
    db = TestingSessionLocal()
    editor_id = ""
    buffett_id = ""
    munger_id = ""
    try:
        editor = _add_author(db, _uid("editor"), "Collected Works Editor")
        buffett = _add_author(
            db,
            _uid("buffett"),
            "Warren Buffett",
            role_type="investor",
            domains=["investing", "business"],
            expertise_tags=["moat", "capital_allocation"],
        )
        munger = _add_author(
            db,
            _uid("munger"),
            "Charlie Munger",
            role_type="investor",
            domains=["investing", "psychology"],
            expertise_tags=["mental_models"],
        )
        editor_id = editor.id
        buffett_id = buffett.id
        munger_id = munger.id

        omnibus = _add_source(db, author_id=editor.id, url="https://example.com/letters")
        _add_document(
            db,
            source_id=str(omnibus.id),
            title="1987 Shareholder Letter",
            clean_text="Stored logical document text for the 1987 shareholder letter.",
            author_id=buffett.id,
            publication_year=1987,
            venue="Annual Meeting",
            collection="Letters",
            canonical_status="canonical",
            work_type="letter",
            source_section="Letter 1987",
            metadata_json={"corpus_section": "Letters"},
            source_document_index=0,
        )
        _add_document(
            db,
            source_id=str(omnibus.id),
            title="1988 Shareholder Letter",
            clean_text="Stored logical document text for the 1988 shareholder letter.",
            author_id=buffett.id,
            publication_year=1988,
            venue="Annual Meeting",
            collection="Letters",
            canonical_status="canonical",
            work_type="letter",
            source_section="Letter 1988",
            metadata_json={"corpus_section": "Letters"},
            source_document_index=1,
        )
        _add_document(
            db,
            source_id=str(omnibus.id),
            title="Munger Lecture",
            clean_text="Munger lecture text stored as a separate logical document.",
            author_id=munger.id,
            publication_year=1990,
            venue="USC",
            collection="Talks",
            canonical_status="canonical",
            work_type="speech",
            source_section="Munger Lecture",
            metadata_json={"corpus_section": "Talks"},
            source_document_index=2,
        )

        legacy_source = _add_source(
            db,
            author_id=buffett.id,
            url="https://example.com/owner-earnings.pdf",
            source_type="pdf",
        )
        _add_document(
            db,
            source_id=str(legacy_source.id),
            title="Owner Earnings",
            clean_text="Legacy single-document ingestion still appears in the reader.",
            author_id=None,
            publication_year=1986,
            collection="Essays",
            canonical_status="canonical",
            work_type="essay",
            source_section="Owner Earnings",
            metadata_json={},
        )
        db.commit()
    finally:
        db.close()

    config_payload = {
        "authors": [
            {
                "id": buffett_id,
                "name": "Warren Buffett",
                "photo_url": "https://example.com/buffett.jpg",
                "about": "Builder of Berkshire Hathaway and steward of the shareholder letters.",
            }
        ]
    }
    with patch("app.routers.rag.load_author_config", return_value=config_payload):
        authors_response = client.get("/rag/library/authors")
    assert authors_response.status_code == 200, authors_response.text
    authors = {author["id"]: author for author in authors_response.json()}

    assert buffett_id in authors
    assert munger_id in authors
    assert editor_id not in authors
    assert authors[buffett_id]["document_count"] == 3
    assert authors[buffett_id]["source_count"] == 2
    assert authors[buffett_id]["photo_url"] == "https://example.com/buffett.jpg"
    assert authors[buffett_id]["about_text"] == (
        "Builder of Berkshire Hathaway and steward of the shareholder letters."
    )
    assert authors[munger_id]["about_text"] == "Investor focused on investing, psychology. Themes: mental models."

    with patch("app.routers.rag.load_author_config", return_value=config_payload):
        library_response = client.get(f"/rag/library/authors/{buffett_id}")
    assert library_response.status_code == 200, library_response.text
    library = library_response.json()

    assert library["author"]["name"] == "Warren Buffett"
    assert library["author"]["photo_url"] == "https://example.com/buffett.jpg"
    assert library["author"]["about_text"] == (
        "Builder of Berkshire Hathaway and steward of the shareholder letters."
    )
    assert library["grouping"]["primary_field"] == "collection"
    assert "collection" in library["grouping"]["available_fields"]

    groups = {group["label"]: group for group in library["groups"]}
    assert set(groups) == {"Letters", "Essays"}
    assert groups["Letters"]["secondary_field"] == "publication_year"
    assert [group["label"] for group in groups["Letters"]["secondary_groups"]] == ["1987", "1988"]

    legacy_document = next(document for document in library["documents"] if document["title"] == "Owner Earnings")
    assert legacy_document["author_id"] == buffett_id
    assert legacy_document["author_name"] == "Warren Buffett"
    assert legacy_document["source_type"] == "pdf"
    assert legacy_document["source_url"] == "https://example.com/owner-earnings.pdf"
    assert legacy_document["canonical_status"] == "canonical"
    assert legacy_document["work_type"] == "essay"


def test_library_document_detail_returns_clean_text_and_parent_child_navigation(client):
    db = TestingSessionLocal()
    parent_id = ""
    child_id = ""
    try:
        buffett = _add_author(db, _uid("buffett"), "Warren Buffett")
        source = _add_source(db, author_id=buffett.id, url="https://example.com/capital-allocation")
        parent = _add_document(
            db,
            source_id=str(source.id),
            title="Capital Allocation",
            clean_text="This is the stored logical-document text for the main capital allocation essay.",
            content_blocks_json=[
                {
                    "block_id": "blk-0000",
                    "type": "heading",
                    "order": 0,
                    "level": 2,
                    "text": "Capital Allocation",
                    "items": None,
                    "table_markdown": None,
                    "table_rows": None,
                    "metadata": {},
                },
                {
                    "block_id": "blk-0001",
                    "type": "paragraph",
                    "order": 1,
                    "level": None,
                    "text": "This is the stored logical-document text for the main capital allocation essay.",
                    "items": None,
                    "table_markdown": None,
                    "table_rows": None,
                    "metadata": {"heading_context": "Capital Allocation"},
                },
                {
                    "block_id": "blk-0002",
                    "type": "list",
                    "order": 2,
                    "level": None,
                    "text": None,
                    "items": ["Retain earnings carefully", "Avoid diworsification"],
                    "table_markdown": None,
                    "table_rows": None,
                    "metadata": {"heading_context": "Capital Allocation"},
                },
                {
                    "block_id": "blk-0003",
                    "type": "table",
                    "order": 3,
                    "level": None,
                    "text": None,
                    "items": None,
                    "table_markdown": "| Metric | Value |\n| --- | --- |\n| ROE | 15% |",
                    "table_rows": [["Metric", "Value"], ["ROE", "15%"]],
                    "metadata": {"heading_context": "Capital Allocation"},
                },
            ],
            author_id=buffett.id,
            publication_year=1994,
            venue="Annual Letter",
            collection="Essays",
            canonical_status="canonical",
            work_type="essay",
            source_section="Capital Allocation",
        )
        child = _add_document(
            db,
            source_id=str(source.id),
            title="Capital Allocation Notes",
            clean_text="Editorial notes that should be linked from the main essay.",
            author_id=buffett.id,
            publication_year=1994,
            collection="Essays",
            work_type="notes",
            source_section="Capital Allocation Notes",
            parent_document_id=str(parent.id),
            source_document_index=1,
        )
        parent_id = str(parent.id)
        child_id = str(child.id)
        db.commit()
    finally:
        db.close()

    parent_response = client.get(f"/rag/library/documents/{parent_id}")
    assert parent_response.status_code == 200, parent_response.text
    parent_body = parent_response.json()
    assert parent_body["clean_text"] == "This is the stored logical-document text for the main capital allocation essay."
    assert parent_body["content_blocks"][0]["type"] == "heading"
    assert parent_body["content_blocks"][1]["type"] == "paragraph"
    assert parent_body["content_blocks"][2]["items"] == ["Retain earnings carefully", "Avoid diworsification"]
    assert parent_body["content_blocks"][3]["table_rows"] == [["Metric", "Value"], ["ROE", "15%"]]
    assert parent_body["source_url"] == "https://example.com/capital-allocation"
    assert parent_body["source_type"] == "html"
    assert parent_body["parent_document"] is None
    assert parent_body["child_documents"][0]["id"] == child_id
    assert parent_body["child_documents"][0]["title"] == "Capital Allocation Notes"

    child_response = client.get(f"/rag/library/documents/{child_id}")
    assert child_response.status_code == 200, child_response.text
    child_body = child_response.json()
    assert child_body["clean_text"] == "Editorial notes that should be linked from the main essay."
    assert child_body["parent_document"]["id"] == parent_id
    assert child_body["parent_document"]["title"] == "Capital Allocation"
    assert child_body["child_documents"] == []
