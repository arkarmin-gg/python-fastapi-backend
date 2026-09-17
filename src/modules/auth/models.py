from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class UserSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    session_key_hash: Mapped[str | None] = mapped_column(String(500), nullable=True)
    device_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    refresh_tokens = relationship("UserRefreshToken", back_populates="session")

    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="expires_after_created"),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="revoked_after_created",
        ),
        Index("user_sessions_user_id_idx", "user_id"),
        Index("user_sessions_user_revoked_at_idx", "user_id", "revoked_at"),
        Index("user_sessions_expires_at_idx", "expires_at"),
    )


class UserRefreshToken(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "user_refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("user_sessions.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    parent_token_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("user_refresh_tokens.id", ondelete="SET NULL"), nullable=True
    )
    replaced_by_token_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("user_refresh_tokens.id", ondelete="SET NULL"), nullable=True
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    session = relationship("UserSession", back_populates="refresh_tokens")

    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="expires_after_created"),
        CheckConstraint("used_at IS NULL OR used_at >= created_at", name="used_after_created"),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="revoked_after_created",
        ),
        Index("user_refresh_tokens_session_id_idx", "session_id"),
        Index("user_refresh_tokens_user_id_idx", "user_id"),
        Index("user_refresh_tokens_session_revoked_at_idx", "session_id", "revoked_at"),
        Index("user_refresh_tokens_expires_at_idx", "expires_at"),
        Index("user_refresh_tokens_parent_token_id_idx", "parent_token_id"),
    )


class UserEmailVerificationToken(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "user_email_verification_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    email_normalized: Mapped[str] = mapped_column(String(255), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("user_email_verification_tokens_user_id_idx", "user_id"),
        Index("user_email_verification_tokens_expires_at_idx", "expires_at"),
    )


class UserPasswordResetToken(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "user_password_reset_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("user_password_reset_tokens_user_id_idx", "user_id"),
        Index("user_password_reset_tokens_expires_at_idx", "expires_at"),
    )
