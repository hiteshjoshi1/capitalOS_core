"""A user's expected cadence for one data source (#252, D-67): migration 080.

No row means the source type's default (``app.services.source_freshness``)."""

from __future__ import annotations

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, Text
from sqlalchemy.sql import func

from .base import Base


class SourceFreshnessOverride(Base):
    __tablename__ = "source_freshness_overrides"

    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    source_key = Column(Text, primary_key=True)
    cadence = Column(Text, nullable=False)
    grace_days = Column(Integer, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
