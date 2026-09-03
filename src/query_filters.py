import re
from collections.abc import Mapping, Sequence
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError
from sqlalchemy import ColumnElement, Select, or_
from sqlalchemy.orm import InstrumentedAttribute

type Column = ColumnElement[Any] | InstrumentedAttribute[Any]
type SortColumn = ColumnElement[Any] | InstrumentedAttribute[Any]

DEFAULT_DATE_FILTER_TIMEZONE = "Asia/Yangon"
DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class SortSpec(BaseModel):
    field: str
    descending: bool = False


def normalize_search(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def require_timezone_aware(value: datetime | None, field_name: str) -> None:
    if value is None:
        return
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{field_name} must include a timezone")


def parse_range_datetime(
    value: str | datetime | None,
    *,
    field_name: str,
    boundary: str,
    timezone: str = DEFAULT_DATE_FILTER_TIMEZONE,
) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value

    if DATE_ONLY_RE.fullmatch(value):
        try:
            parsed_date = datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError as exc:
            raise query_value_error(
                field_name,
                f"{field_name} must be a timezone-aware ISO 8601 datetime or yyyy-mm-dd date",
            ) from exc
    else:
        parsed_date = None

    if parsed_date is not None:
        local_time = time.min if boundary == "from" else time.max
        try:
            tzinfo = ZoneInfo(timezone)
        except ZoneInfoNotFoundError as exc:
            raise query_value_error("timezone", "timezone must be a valid IANA timezone") from exc
        return datetime.combine(parsed_date, local_time, tzinfo=tzinfo)

    normalized_value = value.replace("Z", "+00:00")
    try:
        parsed_datetime = datetime.fromisoformat(normalized_value)
    except ValueError as exc:
        raise query_value_error(
            field_name,
            f"{field_name} must be a timezone-aware ISO 8601 datetime or yyyy-mm-dd date",
        ) from exc

    try:
        require_timezone_aware(parsed_datetime, field_name)
    except ValueError as exc:
        raise query_value_error(field_name, str(exc)) from exc
    return parsed_datetime


def parse_datetime_range(
    from_value: str | datetime | None,
    to_value: str | datetime | None,
    *,
    from_field: str,
    to_field: str,
    timezone: str = DEFAULT_DATE_FILTER_TIMEZONE,
) -> tuple[datetime | None, datetime | None]:
    return (
        parse_range_datetime(from_value, field_name=from_field, boundary="from", timezone=timezone),
        parse_range_datetime(to_value, field_name=to_field, boundary="to", timezone=timezone),
    )


def query_value_error(field_name: str, message: str) -> RequestValidationError:
    return RequestValidationError(
        [{"loc": ["query", field_name], "msg": message, "type": "value_error"}]
    )


def build_query_model[ModelT: BaseModel](model_cls: type[ModelT], **values: Any) -> ModelT:
    try:
        return model_cls(**values)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc


def parse_sort(
    sort: str | None,
    *,
    allowed_fields: set[str],
    default: Sequence[str],
    tie_breaker: str = "id",
) -> tuple[SortSpec, ...]:
    raw_fields = list(default) if sort is None or not sort.strip() else sort.split(",")
    specs: list[SortSpec] = []
    seen: set[str] = set()

    for raw_field in raw_fields:
        field_spec = raw_field.strip()
        if not field_spec:
            raise_sort_error("sort fields cannot be blank")

        descending = field_spec.startswith("-")
        field = field_spec[1:] if descending else field_spec

        if not field:
            raise_sort_error("sort fields cannot be blank")
        if field not in allowed_fields:
            raise_sort_error(f"unsupported sort field: {field}")
        if field in seen:
            raise_sort_error(f"duplicate sort field: {field}")

        seen.add(field)
        specs.append(SortSpec(field=field, descending=descending))

    if tie_breaker not in seen:
        specs.append(SortSpec(field=tie_breaker))

    return tuple(specs)


def apply_sort[StmtT: Select[Any]](
    stmt: StmtT,
    specs: Sequence[SortSpec],
    columns: Mapping[str, SortColumn],
) -> StmtT:
    order_by = []
    for spec in specs:
        column = columns[spec.field]
        order_by.append(column.desc() if spec.descending else column.asc())
    return stmt.order_by(*order_by)


def search_clause(columns: Sequence[SortColumn], value: str | None) -> ColumnElement[bool] | None:
    search = normalize_search(value)
    if search is None:
        return None
    pattern = f"%{_escape_like(search)}%"
    return or_(*(column.ilike(pattern, escape="\\") for column in columns))


def raise_sort_error(message: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=[{"loc": ["query", "sort"], "msg": message, "type": "value_error"}],
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def where_if_not_none[StmtT: Select[Any]](
    stmt: StmtT, column: Column, value: object | None
) -> StmtT:
    if value is None:
        return stmt
    return stmt.where(column == value)


def where_gte_if_not_none[StmtT: Select[Any]](
    stmt: StmtT, column: Column, value: object | None
) -> StmtT:
    if value is None:
        return stmt
    return stmt.where(column >= value)


def where_lte_if_not_none[StmtT: Select[Any]](
    stmt: StmtT, column: Column, value: object | None
) -> StmtT:
    if value is None:
        return stmt
    return stmt.where(column <= value)
