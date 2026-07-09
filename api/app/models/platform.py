from sqlalchemy import BigInteger, Column, DateTime, Text, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .base import Base

# IMPORTANT: This enum name must match the DB enum created by migration: platform_type
PlatformType = Enum(
    "BANK", "BROKER", "EXCHANGE", "CARD_ISSUER", "WALLET_PROVIDER", "MUTUAL_FUND",
    name="platform_type",
    create_type=False,
)

class Platform(Base):
    __tablename__ = "platforms"

    id = Column(BigInteger, primary_key=True)
    code = Column(Text, nullable=False, unique=True)
    name = Column(Text, nullable=False)
    platform_type = Column(PlatformType, nullable=False)
    country = Column(Text, nullable=False)
    website = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    accounts = relationship("Account", back_populates="platform_rel")
