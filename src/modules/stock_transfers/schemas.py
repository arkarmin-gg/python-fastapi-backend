import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import Query
from pydantic import Field, model_validator

from src.foundation_enums import DocumentStatus
from src.pagination import Page
from src.query_filters import build_query_model, parse_datetime_range
from src.schemas import RequestSchema, ResponseSchema


class StockTransferRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    document_no: str
    status: DocumentStatus
    requested_by: uuid.UUID | None
    posted_by: uuid.UUID | None
    posted_at: datetime | None
    cancelled_by: uuid.UUID | None
    cancelled_at: datetime | None
    reversal_of_id: uuid.UUID | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


StockTransferListResponse = Page[StockTransferRead]


class StockTransferFilters(RequestSchema):
    search: str | None = None
    status: DocumentStatus | None = None
    requested_by: uuid.UUID | None = None
    created_at_gte: datetime | None = None
    created_at_lte: datetime | None = None


def stock_transfer_filters(
    search: Annotated[str | None, Query()] = None,
    status: Annotated[DocumentStatus | None, Query()] = None,
    requested_by: Annotated[uuid.UUID | None, Query()] = None,
    created_at_gte: Annotated[str | None, Query()] = None,
    created_at_lte: Annotated[str | None, Query()] = None,
) -> StockTransferFilters:
    from_dt, to_dt = parse_datetime_range(
        created_at_gte,
        created_at_lte,
        from_field="created_at_gte",
        to_field="created_at_lte",
    )
    return build_query_model(
        StockTransferFilters,
        search=search,
        status=status,
        requested_by=requested_by,
        created_at_gte=from_dt,
        created_at_lte=to_dt,
    )


class StockTransferLineRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    stock_transfer_id: uuid.UUID
    line_no: int
    product_variant_id: uuid.UUID
    variant_unit_id: uuid.UUID
    stock_batch_id: uuid.UUID
    quantity: Decimal
    conversion_to_base: Decimal
    quantity_base: Decimal
    from_location_id: uuid.UUID
    to_location_id: uuid.UUID


StockTransferLineListResponse = Page[StockTransferLineRead]


class StockTransferLineFilters(RequestSchema):
    product_variant_id: uuid.UUID | None = None
    stock_batch_id: uuid.UUID | None = None
    variant_unit_id: uuid.UUID | None = None
    from_location_id: uuid.UUID | None = None
    to_location_id: uuid.UUID | None = None


def stock_transfer_line_filters(
    product_variant_id: Annotated[uuid.UUID | None, Query()] = None,
    stock_batch_id: Annotated[uuid.UUID | None, Query()] = None,
    variant_unit_id: Annotated[uuid.UUID | None, Query()] = None,
    from_location_id: Annotated[uuid.UUID | None, Query()] = None,
    to_location_id: Annotated[uuid.UUID | None, Query()] = None,
) -> StockTransferLineFilters:
    return build_query_model(
        StockTransferLineFilters,
        product_variant_id=product_variant_id,
        stock_batch_id=stock_batch_id,
        variant_unit_id=variant_unit_id,
        from_location_id=from_location_id,
        to_location_id=to_location_id,
    )


class StockTransferLineCreate(RequestSchema):
    line_no: int = Field(gt=0)
    product_variant_id: uuid.UUID
    stock_batch_id: uuid.UUID
    variant_unit_id: uuid.UUID
    quantity: Decimal = Field(gt=0, max_digits=24, decimal_places=8)
    from_location_id: uuid.UUID
    to_location_id: uuid.UUID


class StockTransferLineUpdate(RequestSchema):
    line_no: int | None = Field(default=None, gt=0)
    product_variant_id: uuid.UUID | None = None
    stock_batch_id: uuid.UUID | None = None
    variant_unit_id: uuid.UUID | None = None
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=24, decimal_places=8)
    from_location_id: uuid.UUID | None = None
    to_location_id: uuid.UUID | None = None


class StockTransferDetailRead(StockTransferRead):
    lines: list[StockTransferLineRead] = Field(default_factory=list)


class StockTransferCreate(RequestSchema):
    notes: str | None = None
    lines: list[StockTransferLineCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def _no_duplicate_line_numbers(self) -> "StockTransferCreate":
        line_nos = [line.line_no for line in self.lines]
        if len(line_nos) != len(set(line_nos)):
            raise ValueError("lines must not repeat the same line_no.")
        return self


class StockTransferUpdate(RequestSchema):
    notes: str | None = None
