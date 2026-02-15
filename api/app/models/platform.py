from sqlalchemy import BigInteger, Column, Text, Enum
from sqlalchemy.orm import relationship
from .base import Base

# IMPORTANT: This enum name must match the DB enum created by migration: platform_type
PlatformType = Enum(
    "BANK", "BROKER", "EXCHANGE", "CARD_ISSUER", "WALLET_PROVIDER",
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

    accounts = relationship("Account", back_populates="platform_rel")
