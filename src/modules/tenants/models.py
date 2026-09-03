from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.foundation_enums import TenantStatus
from src.models import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum_column


class Tenant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tenants"

    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(250), nullable=True)
    currency_code: Mapped[str] = mapped_column(
        String(3), nullable=False, default="USD", server_default="USD"
    )
    timezone: Mapped[str] = mapped_column(
        String(80), nullable=False, default="UTC", server_default="UTC"
    )
    locale: Mapped[str] = mapped_column(
        String(20), nullable=False, default="en-US", server_default="en-US"
    )
    status: Mapped[TenantStatus] = str_enum_column(
        TenantStatus,
        nullable=False,
        default=TenantStatus.ACTIVE,
        server_default=TenantStatus.ACTIVE.value,
    )

    users = relationship("User", back_populates="tenant")
    roles = relationship("Role", back_populates="tenant")

    __table_args__ = (
        Index("tenants_code_idx", "code"),
        Index("tenants_status_idx", "status"),
    )
