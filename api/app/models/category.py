from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
)
from sqlalchemy.dialects.sqlite import INTEGER as SQLITE_INTEGER
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .base import Base
from .transaction import Transaction  # noqa: F401

SqlId = BigInteger().with_variant(SQLITE_INTEGER(), "sqlite")


class CategoryTaxonomy(Base):
    __tablename__ = "category_taxonomy"

    id = Column(SqlId, primary_key=True)
    code = Column(Text, nullable=False, unique=True)
    name = Column(Text, nullable=False)
    parent_id = Column(SqlId, ForeignKey("category_taxonomy.id", ondelete="SET NULL"), nullable=True)
    display_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    parent = relationship("CategoryTaxonomy", remote_side=[id], back_populates="children")
    children = relationship("CategoryTaxonomy", back_populates="parent")


class CategoryRule(Base):
    __tablename__ = "category_rules"

    id = Column(SqlId, primary_key=True)
    name = Column(Text, nullable=False)
    priority = Column(Integer, nullable=False, default=100)
    merchant_pattern = Column(Text, nullable=True)
    description_pattern = Column(Text, nullable=True)
    source_category_pattern = Column(Text, nullable=True)
    txn_type = Column(Text, nullable=True)
    min_amount = Column(Numeric(38, 18), nullable=True)
    max_amount = Column(Numeric(38, 18), nullable=True)
    target_category_id = Column(SqlId, ForeignKey("category_taxonomy.id"), nullable=False)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    target_category = relationship("CategoryTaxonomy")

    __table_args__ = (
        CheckConstraint(
            "min_amount IS NULL OR max_amount IS NULL OR min_amount <= max_amount",
            name="ck_category_rules_amount_range",
        ),
    )


class CategoryOverride(Base):
    __tablename__ = "category_overrides"

    id = Column(SqlId, primary_key=True)
    transaction_id = Column(SqlId, ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False, unique=True)
    category_id = Column(SqlId, ForeignKey("category_taxonomy.id"), nullable=False)
    source = Column(Text, nullable=False)
    rule_id = Column(SqlId, ForeignKey("category_rules.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    category = relationship("CategoryTaxonomy")
    rule = relationship("CategoryRule")
