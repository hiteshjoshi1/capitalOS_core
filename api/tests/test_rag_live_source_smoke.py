from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("RAG_EMBEDDING_MOCK", "1")
os.environ.setdefault("AUTH_BYPASS_USER_ID", "1")

from app.models.rag import RagAuthor, RagDocument, RagSource
from app.rag.ingestion.pipeline import FAILURE_LOW_QUALITY_EXTRACTION, run_url_ingestion
from tests.conftest import TestingSessionLocal


RUN_LIVE_SOURCE_SMOKE = os.getenv("RUN_LIVE_SOURCE_SMOKE") == "1"


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _add_author(db, author_id: str, name: str) -> RagAuthor:
    author = RagAuthor(id=author_id, name=name, enabled=True)
    db.add(author)
    db.flush()
    return author


@pytest.mark.skipif(
    not RUN_LIVE_SOURCE_SMOKE,
    reason="set RUN_LIVE_SOURCE_SMOKE=1 to run live external-source ingestion smoke checks",
)
class TestRagLiveSourceSmoke:
    def test_stripe_book_page_ingests_real_content(self):
        db = TestingSessionLocal()
        try:
            author = _add_author(db, _uid("munger"), "Charlie Munger")
            source = RagSource(
                user_id=1,
                author_id=author.id,
                url="https://www.stripe.press/poor-charlies-almanack/book?progress=0.00%25",
                source_type="html",
                status="pending",
            )
            db.add(source)
            db.flush()

            job = run_url_ingestion(source, db)
            db.commit()

            documents = db.query(RagDocument).filter(RagDocument.source_id == source.id).all()

            assert job.status == "done"
            assert job.failure_category in (None, "")
            assert len(documents) == 1
            assert len(documents[0].clean_text or "") > 50000
            assert "Chapter Four: Eleven Talks" in (source.clean_text or "")
            assert "The Psychology of Human Misjudgment" in (documents[0].clean_text or "")
        finally:
            db.close()

    def test_stripe_talk_two_page_is_rejected_as_low_quality(self):
        db = TestingSessionLocal()
        try:
            author = _add_author(db, _uid("munger"), "Charlie Munger")
            source = RagSource(
                user_id=1,
                author_id=author.id,
                url="https://www.stripe.press/poor-charlies-almanack/talk-two?progress=0.00%25",
                source_type="html",
                status="pending",
            )
            db.add(source)
            db.flush()

            job = run_url_ingestion(source, db)
            db.commit()

            documents = db.query(RagDocument).filter(RagDocument.source_id == source.id).all()

            assert job.status == "failed"
            assert job.failure_category == FAILURE_LOW_QUALITY_EXTRACTION
            assert documents == []
        finally:
            db.close()

    def test_stripe_book_page_fanout_persists_two_logical_documents_with_metadata(self):
        db = TestingSessionLocal()
        try:
            munger = _add_author(db, _uid("munger"), "Charlie Munger")
            collison = _add_author(db, _uid("collison"), "John Collison")
            source = RagSource(
                user_id=1,
                author_id=munger.id,
                url="https://www.stripe.press/poor-charlies-almanack/book?progress=0.00%25",
                source_type="html",
                status="pending",
                ingestion_config={
                    "mode": "fanout",
                    "documents": [
                        {
                            "key": "collison-foreword",
                            "title": "Foreword: Collison on Munger",
                            "author_id": collison.id,
                            "collection": "Poor Charlie's Almanack",
                            "canonical_status": "context",
                            "source_section": "Foreword: Collison on Munger",
                            "work_type": "foreword",
                            "selective_options": {"include_headings": ["Foreword: Collison on Munger"]},
                        },
                        {
                            "key": "recommended-reading",
                            "title": "Recommended reading",
                            "author_id": munger.id,
                            "collection": "Poor Charlie's Almanack",
                            "canonical_status": "reference",
                            "source_section": "Recommended reading",
                            "work_type": "reference",
                            "selective_options": {"include_headings": ["Recommended reading"]},
                        },
                    ],
                },
            )
            db.add(source)
            db.flush()

            job = run_url_ingestion(source, db)
            db.commit()

            documents = (
                db.query(RagDocument)
                .filter(RagDocument.source_id == source.id)
                .order_by(RagDocument.source_document_index.asc())
                .all()
            )

            assert job.status == "done"
            assert job.failure_category in (None, "")
            assert job.stats_json["ingestion_mode"] == "fanout"
            assert job.stats_json["documents_created"] == 2
            assert len(source.clean_text or "") > 50000
            assert len(documents) == 2

            foreword, reading = documents
            assert foreword.title == "Foreword: Collison on Munger"
            assert foreword.author_id == collison.id
            assert foreword.collection == "Poor Charlie's Almanack"
            assert foreword.work_type == "foreword"
            assert foreword.source_section == "Foreword: Collison on Munger"
            assert "John Collison" in (foreword.clean_text or "")
            assert "Recommended reading" not in (foreword.clean_text or "")

            assert reading.title == "Recommended reading"
            assert reading.author_id == munger.id
            assert reading.collection == "Poor Charlie's Almanack"
            assert reading.work_type == "reference"
            assert reading.source_section == "Recommended reading"
            assert "Titan: The Life of John D. Rockefeller" in (reading.clean_text or "")
            assert "Foreword: Collison on Munger" not in (reading.clean_text or "")
        finally:
            db.close()
