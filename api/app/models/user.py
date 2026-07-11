from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Text, func

from .base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True)
    username = Column(Text, nullable=False, unique=True)
    display_name = Column(Text, nullable=True)
    email = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    is_admin = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class UserCredential(Base):
    __tablename__ = "user_credentials"

    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    password_hash = Column(Text, nullable=False)
    password_algo = Column(Text, nullable=False)
    password_updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    refresh_token_hash = Column(Text, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OAuthIdentity(Base):
    __tablename__ = "oauth_identities"

    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider = Column(Text, nullable=False)
    provider_subject = Column(Text, nullable=False)
    email = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class UserPreference(Base):
    __tablename__ = "user_preferences"

    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    theme = Column(Text, nullable=False, default="dark")
    accent_color = Column(Text, nullable=False, default="#0f7a5c")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
