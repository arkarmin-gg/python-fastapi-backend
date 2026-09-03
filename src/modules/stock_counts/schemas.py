import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import Query
from pydantic import Field

from src.foundation_enums import DocumentStatus
from src.pagination import Page
from src.query_filters import build_query_model, parse_datetime_range
from src.schemas import RequestSchema, ResponseSchema


class StockCountRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    document_no: str
    location_id: uuid.UUID
    counted_at: datetime
    counted_by: uuid.UUID
    status: DocumentStatus
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    posted_by: uuid.UUID | None
    posted_at: datetime | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


StockCountListResponse = Page[StockCountRead]


class StockCountFilters(RequestSchema):
    search: str | None = None
    location_id: uuid.UUID | None = None
    status: DocumentStatus | None = None
    counted_at_gte: datetime | None = None
    counted_at_lte: datetime | None = None


def stock_count_filters(
    search: Annotated[str | None, Query()] = None,
    location_id: Annotated[uuid.UUID | None, Query()] = None,
    status: Annotated[DocumentStatus | None, Query()] = None,
    counted_at_gte: Annotated[str | None, Query()] = None,
    counted_at_lte: Annotated[str | None, Query()] = None,
) -> StockCountFilters:
    from_dt, to_dt = parse_datetime_range(
        counted_at_gte,
        counted_at_lte,
        from_field="counted_at_gte",
        to_field="counted_at_lte",
    )
    return build_query_model(
        StockCountFilters,
        search=search,
        location_id=location_id,
        status=status,
        counted_at_gte=from_dt,
        counted_at_lte=to_dt,
    )


class StockCountCreate(RequestSchema):
    location_id: uuid.UUID
    counted_at: datetime | None = None
    notes: str | None = None


class StockCountUpdate(RequestSchema):
    location_id: uuid.UUID | None = None
    counted_at: datetime | None = None
    notes: str | None = None


class StockCountLineRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    stock_count_id: uuid.UUID
    line_no: int
    product_variant_id: uuid.UUID
    stock_batch_id: uuid.UUID
    expected_quantity_base: Decimal
    counted_quantity_base: Decimal
    variance_quantity_base: Decimal
    adjustment_movement_id: uuid.UUID | None
    notes: str | None


StockCountLineListResponse = Page[StockCountLineRead]


class StockCountLineFilters(RequestSchema):
    product_variant_id: uuid.UUID | None = None
    stock_batch_id: uuid.UUID | None = None


def stock_count_line_filters(
    product_variant_id: Annotated[uuid.UUID | None, Query()] = None,
    stock_batch_id: Annotated[uuid.UUID | None, Query()] = None,
) -> StockCountLineFilters:
    return build_query_model(
        StockCountLineFilters,
        product_variant_id=product_variant_id,
        stock_batch_id=stock_batch_id,
    )


class StockCountLineCreate(RequestSchema):
    line_no: int = Field(gt=0)
    product_variant_id: uuid.UUID
    stock_batch_id: uuid.UUID
    counted_quantity_base: Decimal = Field(ge=0, max_digits=24, decimal_places=8)
    notes: str | None = None


class StockCountLineUpdate(RequestSchema):
    line_no: int | None = Field(default=None, gt=0)
    product_variant_id: uuid.UUID | None = None
    stock_batch_id: uuid.UUID | None = None
    counted_quantity_base: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=24,
        decimal_places=8,
    )
    notes: str | None = None


class StockCountDetailRead(StockCountRead):
    lines: list[StockCountLineRead] = Field(default_factory=list)
