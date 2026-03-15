from sqlalchemy import BigInteger, Column, DateTime, Float, Text
from sqlalchemy.dialects.sqlite import INTEGER as SQLITE_INTEGER

from .base import Base

SqlId = BigInteger().with_variant(SQLITE_INTEGER(), "sqlite")


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(SqlId, primary_key=True)
    ts = Column(DateTime(timezone=True), nullable=False)
    account_id = Column(SqlId, nullable=False)
    amount = Column(Float, nullable=False)
    type = Column(Text, nullable=False)
    currency = Column(Text, nullable=False)
    category = Column(Text, nullable=True)
    merchant_counterparty = Column(Text, nullable=True)
    platform_reference = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    source = Column(Text, nullable=True)
