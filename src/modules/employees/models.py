import uuid
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Employee(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "employees"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    position: Mapped[str | None] = mapped_column(String(120), nullable=True)
    joined_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    tenant = relationship("Tenant", back_populates="employees")
    users = relationship("User", back_populates="employee")
    location_assignments = relationship("LocationAssignment", back_populates="employee")
    repack_orders = relationship("RepackOrder", back_populates="performed_by_employee")

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="employees_tenant_id_code_key"),
        Index("employees_tenant_id_name_idx", "tenant_id", "name"),
        Index("employees_tenant_id_is_active_idx", "tenant_id", "is_active"),
    )
