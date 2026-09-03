from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from src.exceptions import AppException


class ErrorResponse(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
    )

    error_code: str = Field(description="A stable, machine-readable error identifier.")
    detail: str = Field(description="A human-readable explanation of the error.")
    details: dict[str, Any] | None = Field(
        default=None,
        description="Optional structured context for machine-assisted recovery.",
    )


class RequestSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        populate_by_name=True,
    )


class ResponseSchema(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )

    @field_serializer("*")
    def serialize_decimal(self, value):
        if isinstance(value, Decimal):
            return format(value, "f")

        return value


def error_responses(
    *exceptions: type[AppException],
) -> dict[int | str, dict[str, Any]]:
    grouped: dict[int, list[str]] = {}

    for exc in exceptions:
        grouped.setdefault(
            exc.status_code,
            [],
        ).append(f"`{exc.error_code}`: {exc.detail}")

    return {
        code: {
            "model": ErrorResponse,
            "description": "\n\n".join(lines),
        }
        for code, lines in grouped.items()
    }
