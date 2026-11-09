"""A user's choice to show or hide one wallet token (#342, D-87): migration 083.

No row means automatic (``app.crypto.token_visibility``)."""

from __future__ import annotations

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Text
from sqlalchemy.sql import func

from .base import Base


class CryptoTokenVisibility(Base):
    __tablename__ = "crypto_token_visibility"

    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    chain = Column(Text, primary_key=True)
    contract_or_mint = Column(Text, primary_key=True)
    visibility = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
