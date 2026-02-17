from sqlalchemy import BigInteger, Column, Text, Enum, ForeignKey
from sqlalchemy.orm import relationship
from .base import Base

# enum name must match DB enum: account_type
AccountType = Enum(
    "BANK", "BROKER", "EXCHANGE", "WALLET", "CREDIT_CARD", "LOAN", "MUTUAL_FUND",
    name="account_type",
    create_type=False,
)

class Account(Base):
    __tablename__ = "accounts"

    id = Column(BigInteger, primary_key=True)
    name = Column(Text, nullable=False)

    # legacy column from your initial schema
    platform = Column(Text, nullable=False)

    account_type = Column(AccountType, nullable=False)
    currency = Column(Text, nullable=False)
    country = Column(Text, nullable=True)

    # FK to platforms (added later)
    platform_id = Column(BigInteger, ForeignKey("platforms.id"), nullable=True)

    # relationship (ensure Platform model uses back_populates="platform")
    platform_rel = relationship("Platform", back_populates="accounts")
