from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, Column, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import relationship

from .base import Base


def _uuid_str() -> str:
    return str(uuid.uuid4())


class AISageChat(Base):
    __tablename__ = "ai_sage_chats"

    id = Column(String(36), primary_key=True, default=_uuid_str)
    owner_user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(Text, nullable=False, default="New chat")
    last_activity_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, index=True)
    pinned_at = Column(DateTime(timezone=True), nullable=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = relationship(
        "AISageMessage",
        back_populates="chat",
        cascade="all, delete-orphan",
        order_by="(AISageMessage.created_at, AISageMessage.id)",
    )


class AISageMessage(Base):
    __tablename__ = "ai_sage_messages"

    id = Column(String(36), primary_key=True, default=_uuid_str)
    chat_id = Column(String(36), ForeignKey("ai_sage_chats.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(32), nullable=False)
    content = Column(Text, nullable=False, default="")
    status = Column(String(32), nullable=False, default="completed")
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, index=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    metadata_json = Column(JSON, nullable=True)

    chat = relationship("AISageChat", back_populates="messages")
    evidence = relationship(
        "AISageTurnEvidence",
        back_populates="message",
        cascade="all, delete-orphan",
        order_by="AISageTurnEvidence.id",
    )


class AISageTurnEvidence(Base):
    __tablename__ = "ai_sage_turn_evidence"

    id = Column(String(36), primary_key=True, default=_uuid_str)
    message_id = Column(String(36), ForeignKey("ai_sage_messages.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_id = Column(String(64), nullable=True)
    document_id = Column(String(64), nullable=True)
    author_id = Column(String(128), nullable=True)
    author_name = Column(Text, nullable=True)
    source_url = Column(Text, nullable=True)
    title = Column(Text, nullable=True)
    snippet = Column(Text, nullable=True)
    similarity = Column(Float, nullable=True)
    ranking_score = Column(Float, nullable=True)
    score_type = Column(String(64), nullable=True)
    metadata_json = Column(JSON, nullable=True)

    message = relationship("AISageMessage", back_populates="evidence")
