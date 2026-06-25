"""
SQLAlchemy ORM model for the canonical account balance snapshot table.

account_balance_snapshots is the canonical storage for non-security balances
(cash, bank balances, broker cash, stablecoin cash, etc.) at the account level.

Design rules:
- balance_type must be one of: cash | broker_cash | bank_cash |
  credit_balance | loan_balance | stablecoin_cash
- authority_status must be one of: authoritative | reference | superseded
- source_kind must be one of: upload_parser | flex | backfill | manual_adjustment
- Only one authoritative row per (account_id, as_of_date, currency, balance_type).
  This uniqueness is enforced by a partial unique index in the DB.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Column, Date, ForeignKey, Integer, Numeric, Text

from .base import Base


class AccountBalanceSnapshot(Base):
    """Canonical account-level cash/balance snapshot.

    Replaces the legacy pattern of encoding cash as positions(asset_class='CASH').
    Bank accounts, broker cash, and other cash-like balances are account-level
    facts and belong here.
    """

    __tablename__ = "account_balance_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Core lineage
    account_id = Column(
        BigInteger, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    broker_account_id = Column(BigInteger, nullable=True)
    import_job_id = Column(
        BigInteger, ForeignKey("import_jobs.id", ondelete="SET NULL"), nullable=True
    )
    broker_import_run_id = Column(BigInteger, nullable=True)
    raw_document_id = Column(BigInteger, nullable=True)

    # Temporal key
    as_of_date = Column(Date, nullable=False)

    # Balance detail
    currency = Column(Text, nullable=False)
    balance_type = Column(Text, nullable=False, default="cash")
    balance_local = Column(Numeric(38, 18), nullable=False)
    balance_base = Column(Numeric(38, 18), nullable=False)
    fx_rate_to_base = Column(Numeric(38, 18), nullable=False, default=1)

    # Source provenance
    authority_status = Column(Text, nullable=False, default="authoritative")
    source_kind = Column(Text, nullable=False)
    source_row_hash = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=True)

    # Timestamps are managed at the DB level via DEFAULT; the ORM model exposes
    # them as read-only columns for query purposes.
    created_at = Column(Text, nullable=True)
    updated_at = Column(Text, nullable=True)
