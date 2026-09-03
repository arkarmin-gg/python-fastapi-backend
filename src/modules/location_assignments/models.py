import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.foundation_enums import AssignmentRole
from src.models import Base, UUIDPrimaryKeyMixin, str_enum_column


class LocationAssignment(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "location_assignments"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[AssignmentRole] = str_enum_column(
        AssignmentRole,
        nullable=False,
        default=AssignmentRole.RESPONSIBLE,
        server_default=AssignmentRole.RESPONSIBLE.value,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    tenant = relationship("Tenant", back_populates="location_assignments")
    location = relationship("Location", back_populates="assignments")
    employee = relationship("Employee", back_populates="location_assignments")

    __table_args__ = (
        Index(
            "location_assignments_tenant_id_location_id_start_date_idx",
            "tenant_id",
            "location_id",
            "start_date",
        ),
        Index(
            "location_assignments_tenant_id_employee_id_start_date_idx",
            "tenant_id",
            "employee_id",
            "start_date",
        ),
    )
