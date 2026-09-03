import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.foundation_enums import LocationType
from src.models import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum_column


class Location(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "locations"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    parent_location_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="SET NULL"), nullable=True
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    location_type: Mapped[LocationType] = str_enum_column(LocationType, nullable=False)
    is_sellable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    tenant = relationship("Tenant", back_populates="locations")
    parent_location = relationship(
        "Location",
        remote_side="Location.id",
        back_populates="child_locations",
    )
    child_locations = relationship("Location", back_populates="parent_location")
    assignments = relationship("LocationAssignment", back_populates="location")
    purchase_invoice_lines = relationship("PurchaseInvoiceLine", back_populates="location")
    stock_adjustments = relationship("StockAdjustment", back_populates="location")
    stock_counts = relationship("StockCount", back_populates="location")
    repack_orders = relationship("RepackOrder", back_populates="location")
    stock_transfer_lines_from = relationship(
        "StockTransferLine",
        foreign_keys="StockTransferLine.from_location_id",
        back_populates="from_location",
    )
    stock_transfer_lines_to = relationship(
        "StockTransferLine",
        foreign_keys="StockTransferLine.to_location_id",
        back_populates="to_location",
    )
    variant_location_settings = relationship("VariantLocationSetting", back_populates="location")
    sales_invoices = relationship("SalesInvoice", back_populates="location")
    sales_invoice_line_locations = relationship(
        "SalesInvoiceLineLocation", back_populates="location"
    )
    stock_movements = relationship("StockMovement", back_populates="location")
    stock_balances = relationship("StockBalance", back_populates="location")

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="locations_tenant_id_code_key"),
        Index("locations_tenant_id_parent_location_id_idx", "tenant_id", "parent_location_id"),
        Index("locations_tenant_id_location_type_idx", "tenant_id", "location_type"),
    )
