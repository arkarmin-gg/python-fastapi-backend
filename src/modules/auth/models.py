import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from src.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class UserRefreshToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_refresh_tokens"

    token_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("user_refresh_tokens_token_hash_idx", "token_hash"),
        Index("user_refresh_tokens_tenant_id_user_id_idx", "tenant_id", "user_id"),
        Index("user_refresh_tokens_expires_at_idx", "expires_at"),
        Index("user_refresh_tokens_user_id_revoked_at_idx", "user_id", "revoked_at"),
    )
