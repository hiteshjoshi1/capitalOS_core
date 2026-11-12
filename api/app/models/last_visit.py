"""When the user last looked at Overview and the net worth shown then (#408, U3, D-112): migration 086."""

from __future__ import annotations

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Numeric, Text

from .base import Base


class UserLastVisit(Base):
    __tablename__ = "user_last_visit"

    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    seen_at = Column(DateTime(timezone=True), nullable=False)
    net_worth = Column(Numeric(38, 2))
    base_currency = Column(Text)
