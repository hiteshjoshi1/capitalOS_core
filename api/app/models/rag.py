"""SQLAlchemy ORM models for RAG Phase 1 tables."""

import uuid
from datetime import datetime, date
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    DateTime,
    TypeDecorator,
    types,
)
from sqlalchemy.orm import relationship

from app.models.base import Base

# ── Dialect-aware column types ────────────────────────────────────────────────
# Use native Postgres types in production; fall back to JSON/Text for SQLite.


class _StringList(TypeDecorator):
    """TEXT[] on Postgres, JSON array on SQLite."""

    impl = types.Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import ARRAY
            return dialect.type_descriptor(ARRAY(String))
        return dialect.type_descriptor(types.Text)

    def process_bind_param(self, value, dialect):
        if dialect.name == "postgresql":
            return value or []
        import json
        return json.dumps(value or [])

    def process_result_value(self, value, dialect):
        if dialect.name == "postgresql":
            return value or []
        if value is None:
            return []
        import json
        return json.loads(value)


class _JsonBlob(TypeDecorator):
    """JSONB on Postgres, JSON (text) on SQLite."""

    impl = types.Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import JSONB
            return dialect.type_descriptor(JSONB)
        return dialect.type_descriptor(types.Text)

    def process_bind_param(self, value, dialect):
        if dialect.name == "postgresql":
            return value if value is not None else {}
        import json
        return json.dumps(value if value is not None else {})

    def process_result_value(self, value, dialect):
        if dialect.name == "postgresql":
            return value if value is not None else {}
        if value is None:
            return {}
        import json
        return json.loads(value)


class _UUIDStr(TypeDecorator):
    """Native UUID on Postgres, CHAR(36) string on SQLite."""

    impl = types.String
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import UUID
            return dialect.type_descriptor(UUID(as_uuid=True))
        return dialect.type_descriptor(types.String(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value  # UUID object or string both work
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        return str(value)


def _uuid_default():
    return str(uuid.uuid4())


# ── Dialect-aware tsvector type ───────────────────────────────────────────────


class _TsVector(TypeDecorator):
    """TSVECTOR on Postgres, Text (ignored) on SQLite.

    Only used for ORM schema reflection; actual FTS queries bypass the ORM.
    """

    impl = types.Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import TSVECTOR
            return dialect.type_descriptor(TSVECTOR())
        return dialect.type_descriptor(types.Text)

    def process_bind_param(self, value, dialect):
        return value

    def process_result_value(self, value, dialect):
        return value


# ── pgvector Vector type (optional) ──────────────────────────────────────────

try:
    from pgvector.sqlalchemy import Vector as PgVector  # type: ignore

    _VECTOR_TYPE = PgVector(1024)
except Exception:  # pragma: no cover
    # pgvector Python package not installed; use Text as a non-functional stand-in.
    # The real column is created via SQL migration with the correct type.
    _VECTOR_TYPE = types.Text()  # type: ignore


class RagAuthor(Base):
    __tablename__ = "rag_authors"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    domains = Column(_StringList, nullable=False, default=list)
    expertise_tags = Column(_StringList, nullable=False, default=list)
    overall_weight = Column(Float, nullable=False, default=1.0)
    role_type = Column(String)
    config_source = Column(String, nullable=False, default="config/rag_authors.yaml")
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    card = relationship("RagAuthorCard", back_populates="author", uselist=False, cascade="all, delete-orphan")
    sources = relationship("RagSource", back_populates="author", cascade="all, delete-orphan")


class RagAuthorCard(Base):
    __tablename__ = "rag_author_cards"

    author_id = Column(String, ForeignKey("rag_authors.id", ondelete="CASCADE"), primary_key=True)
    focus_areas = Column(_StringList, nullable=False, default=list)
    avoid_patterns = Column(_StringList, nullable=False, default=list)
    biases = Column(_StringList, nullable=False, default=list)
    prompt_adapter = Column(_JsonBlob, nullable=False, default=dict)
    enabled = Column(Boolean, nullable=False, default=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    author = relationship("RagAuthor", back_populates="card")


class RagSource(Base):
    __tablename__ = "rag_sources"

    id = Column(_UUIDStr, primary_key=True, default=_uuid_default)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    author_id = Column(String, ForeignKey("rag_authors.id", ondelete="CASCADE"), nullable=False)
    url = Column(Text)
    source_type = Column(String, nullable=False)  # html | pdf | text | manual
    status = Column(String, nullable=False, default="pending")  # pending | queued | running | failed | ingested
    hash = Column(String)
    selective_options = Column(_JsonBlob, nullable=True)  # optional selective ingestion rules
    last_ingested_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    author = relationship("RagAuthor", back_populates="sources")
    documents = relationship("RagDocument", back_populates="source", cascade="all, delete-orphan")
    jobs = relationship("RagIngestionJob", back_populates="source", cascade="all, delete-orphan")


class RagDocument(Base):
    __tablename__ = "rag_documents"

    id = Column(_UUIDStr, primary_key=True, default=_uuid_default)
    source_id = Column(_UUIDStr, ForeignKey("rag_sources.id", ondelete="CASCADE"), nullable=False)
    title = Column(Text)
    published_at = Column(Date)
    raw_text = Column(Text)
    clean_text = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    source = relationship("RagSource", back_populates="documents")
    chunks = relationship("RagChunk", back_populates="document", cascade="all, delete-orphan")


class RagChunk(Base):
    __tablename__ = "rag_chunks"

    id = Column(_UUIDStr, primary_key=True, default=_uuid_default)
    document_id = Column(_UUIDStr, ForeignKey("rag_documents.id", ondelete="CASCADE"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    token_count = Column(Integer)
    metadata_json = Column(_JsonBlob, nullable=False, default=dict)
    tsv = Column(_TsVector, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    document = relationship("RagDocument", back_populates="chunks")
    embedding = relationship("RagEmbedding", back_populates="chunk", uselist=False, cascade="all, delete-orphan")


class RagEmbedding(Base):
    __tablename__ = "rag_embeddings"

    chunk_id = Column(_UUIDStr, ForeignKey("rag_chunks.id", ondelete="CASCADE"), primary_key=True)
    embedding = Column(_VECTOR_TYPE, nullable=False)
    model = Column(String, nullable=False, default="voyage-4")
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    chunk = relationship("RagChunk", back_populates="embedding")


class RagAuthorProfile(Base):
    __tablename__ = "rag_author_profiles"

    id = Column(_UUIDStr, primary_key=True, default=_uuid_default)
    author_id = Column(String, ForeignKey("rag_authors.id", ondelete="CASCADE"), nullable=False, unique=True)
    worldview = Column(Text)
    key_maxims = Column(_StringList, nullable=False, default=list)
    strengths = Column(_StringList, nullable=False, default=list)
    weaknesses = Column(_StringList, nullable=False, default=list)
    favored_decision_variables = Column(_StringList, nullable=False, default=list)
    anti_patterns = Column(_StringList, nullable=False, default=list)
    generation_model = Column(String, nullable=False, default="template")
    corpus_chunk_count = Column(Integer, nullable=False, default=0)
    generated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    author = relationship("RagAuthor", backref="profile", uselist=False)
    citations = relationship("RagAuthorProfileCitation", back_populates="profile", cascade="all, delete-orphan")


class RagAuthorProfileCitation(Base):
    __tablename__ = "rag_author_profile_citations"

    id = Column(_UUIDStr, primary_key=True, default=_uuid_default)
    profile_id = Column(_UUIDStr, ForeignKey("rag_author_profiles.id", ondelete="CASCADE"), nullable=False)
    chunk_id = Column(_UUIDStr, ForeignKey("rag_chunks.id", ondelete="CASCADE"), nullable=False)
    citation_context = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    profile = relationship("RagAuthorProfile", back_populates="citations")
    chunk = relationship("RagChunk")


class RagIngestionJob(Base):
    __tablename__ = "rag_ingestion_jobs"

    id = Column(_UUIDStr, primary_key=True, default=_uuid_default)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    source_id = Column(_UUIDStr, ForeignKey("rag_sources.id", ondelete="CASCADE"), nullable=False)
    batch_id = Column(_UUIDStr)
    status = Column(String, nullable=False, default="pending")  # pending | queued | running | done | failed
    failure_category = Column(String)
    error = Column(Text)
    stats_json = Column(_JsonBlob, nullable=False, default=dict)
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    source = relationship("RagSource", back_populates="jobs")


class RealtimeEvent(Base):
    __tablename__ = "realtime_events"

    id = Column(_UUIDStr, primary_key=True, default=_uuid_default)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    topic = Column(String, nullable=False)
    event_name = Column(String, nullable=False)
    batch_id = Column(_UUIDStr)
    author_id = Column(String)
    source_id = Column(_UUIDStr)
    job_id = Column(_UUIDStr)
    status = Column(String)
    payload = Column(_JsonBlob, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


# ── Retrieval evaluation models ───────────────────────────────────────────────


class RagQuery(Base):
    __tablename__ = "rag_queries"

    id = Column(_UUIDStr, primary_key=True, default=_uuid_default)
    query_text = Column(Text, nullable=False)
    mode = Column(String(64))
    intent_json = Column(_JsonBlob, nullable=False, default=dict)
    retrieval_config = Column(_JsonBlob, nullable=False, default=dict)
    answer_text = Column(Text)
    latency_ms = Column(Integer)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    evidence = relationship("RagQueryEvidence", back_populates="query", cascade="all, delete-orphan")


class RagQueryEvidence(Base):
    __tablename__ = "rag_query_evidence"

    id = Column(_UUIDStr, primary_key=True, default=_uuid_default)
    query_id = Column(_UUIDStr, ForeignKey("rag_queries.id", ondelete="CASCADE"), nullable=False)
    chunk_id = Column(_UUIDStr, ForeignKey("rag_chunks.id", ondelete="CASCADE"), nullable=False)
    rank = Column(Integer, nullable=False)
    cosine_distance = Column(Float)
    reranker_score = Column(Float)
    rrf_score = Column(Float)
    ts_rank = Column(Float)
    is_golden = Column(Boolean, nullable=False, default=False)

    query = relationship("RagQuery", back_populates="evidence")
    chunk = relationship("RagChunk")


class RagEvalGolden(Base):
    __tablename__ = "rag_eval_golden"

    id = Column(_UUIDStr, primary_key=True, default=_uuid_default)
    query_text = Column(Text, nullable=False)
    chunk_id = Column(_UUIDStr, ForeignKey("rag_chunks.id", ondelete="CASCADE"), nullable=False)
    relevance_grade = Column(Integer, nullable=False, default=1)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    chunk = relationship("RagChunk")
