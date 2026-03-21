from __future__ import annotations

import uuid
from sqlalchemy import Column, Text, Date, DateTime, Boolean, BigInteger, Numeric, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from .base import Base


class CryptoWallet(Base):
    __tablename__ = "crypto_wallets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(BigInteger, nullable=True)
    chain_type = Column(Text, nullable=False)
    chain = Column(Text, nullable=False)
    address = Column(Text, nullable=False)
    label = Column(Text, nullable=True)
    status = Column(Text, nullable=False, default="pending_verification")
    refresh_in_progress = Column(Boolean, nullable=False, default=False)
    refresh_started_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    verified_at = Column(DateTime(timezone=True), nullable=True)


class CryptoWalletVerification(Base):
    __tablename__ = "crypto_wallet_verifications"

    id = Column(BigInteger, primary_key=True)
    wallet_id = Column(UUID(as_uuid=True), nullable=True)
    chain_type = Column(Text, nullable=True)
    chain = Column(Text, nullable=True)
    address = Column(Text, nullable=True)
    nonce = Column(Text, nullable=False)
    message = Column(Text, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)


class CryptoAsset(Base):
    __tablename__ = "crypto_assets"

    id = Column(BigInteger, primary_key=True)
    chain_type = Column(Text, nullable=False)
    chain = Column(Text, nullable=False)
    asset_kind = Column(Text, nullable=False)
    contract_or_mint = Column(Text, nullable=True)
    symbol = Column(Text, nullable=True)
    name = Column(Text, nullable=True)
    decimals = Column(BigInteger, nullable=True)
    base_asset = Column(Text, nullable=True)


class CryptoWalletSnapshot(Base):
    __tablename__ = "crypto_wallet_snapshots"

    id = Column(BigInteger, primary_key=True)
    wallet_id = Column(UUID(as_uuid=True), nullable=False)
    as_of_date = Column(Date, nullable=False)
    fetched_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    total_usd = Column(Numeric, nullable=True)
    source_versions = Column(JSONB, nullable=True)


class CryptoWalletSnapshotItem(Base):
    __tablename__ = "crypto_wallet_snapshot_items"

    id = Column(BigInteger, primary_key=True)
    snapshot_id = Column(BigInteger, nullable=False)
    asset_id = Column(BigInteger, nullable=True)
    chain_type = Column(Text, nullable=False)
    chain = Column(Text, nullable=False)
    asset_kind = Column(Text, nullable=False)
    contract_or_mint = Column(Text, nullable=True)
    symbol = Column(Text, nullable=True)
    name = Column(Text, nullable=True)
    decimals = Column(BigInteger, nullable=True)
    raw_amount = Column(Text, nullable=True)
    normalized_amount = Column(Numeric, nullable=True)
    price_usd = Column(Numeric, nullable=True)
    value_usd = Column(Numeric, nullable=True)
    price_source = Column(Text, nullable=True)


class CryptoUserNetworth(Base):
    __tablename__ = "crypto_user_networth"

    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, nullable=True)
    as_of_date = Column(Date, nullable=False)
    total_usd = Column(Numeric, nullable=True)
    crypto_usd = Column(Numeric, nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
