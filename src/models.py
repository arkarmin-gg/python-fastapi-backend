import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, MetaData, Uuid, func, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "%(column_0_label)s_idx",
    "uq": "%(table_name)s_%(column_0_name)s_key",
    "ck": "%(table_name)s_%(constraint_name)s_check",
    "fk": "%(table_name)s_%(column_0_name)s_fkey",
    "pk": "%(table_name)s_pkey",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


def str_enum_column[EnumT: StrEnum](
    enum_cls: type[EnumT], length: int = 50, **kwargs: Any
) -> Mapped[EnumT]:
    return mapped_column(
        SAEnum(
            enum_cls,
            native_enum=False,
            length=length,
            values_callable=lambda e: [member.value for member in e],
            validate_strings=True,
        ),
        **kwargs,
    )
