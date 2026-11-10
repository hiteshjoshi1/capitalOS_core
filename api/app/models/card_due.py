"""What one card statement says is due, and by when (#352, D-91): migration 084.

No row means the card's due date is unknown; it is never guessed (``app.valuation.card_dues``)."""

from __future__ import annotations

from sqlalchemy import BigInteger, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, Numeric, Text, UniqueConstraint
from sqlalchemy.sql import func

from .base import Base


class CardStatementDue(Base):
    __tablename__ = "card_statement_dues"
    __table_args__ = (
        CheckConstraint("due_date >= statement_date", name="card_statement_dues_due_after_statement"),
        CheckConstraint("source IN ('statement', 'manual')", name="card_statement_dues_source_check"),
        UniqueConstraint("account_id", "statement_date", name="card_statement_dues_one_per_statement"),
    )

    id = Column(BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True)
    account_id = Column(BigInteger, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    statement_date = Column(Date, nullable=False)
    due_date = Column(Date, nullable=False)
    amount_due = Column(Numeric(38, 2))
    minimum_due = Column(Numeric(38, 2))
    source = Column(Text, nullable=False)
    import_job_id = Column(BigInteger, ForeignKey("import_jobs.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
