from sqlalchemy import Boolean, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation_enums import UnitKind
from src.models import Base, UUIDPrimaryKeyMixin, str_enum_column


class Unit(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "units"

    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name_en: Mapped[str] = mapped_column(String(120), nullable=False)
    name_my: Mapped[str | None] = mapped_column(String(120), nullable=True)
    unit_kind: Mapped[UnitKind] = str_enum_column(UnitKind, nullable=False)
    is_global: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    __table_args__ = (
        Index("units_code_idx", "code"),
        Index("units_unit_kind_idx", "unit_kind"),
        Index("units_is_active_idx", "is_active"),
    )
