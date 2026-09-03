import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import Query
from pydantic import Field, field_validator, model_validator

from src.foundation_enums import DocumentStatus, StockAdjustmentReason
from src.modules.document_numbers.service import is_generated_lot_number
from src.pagination import Page
from src.query_filters import build_query_model, parse_datetime_range
from src.schemas import RequestSchema, ResponseSchema


class LotNumberRequestSchema(RequestSchema):
    @field_validator("lot_number", check_fields=False)
    @classmethod
    def _manual_lot_must_not_use_generated_format(cls, value: str | None) -> str | None:
        if value is not None and is_generated_lot_number(value):
            raise ValueError("LOT-YYYYMM-NNNNNN is reserved for server-generated lot numbers.")
        return value


class StockAdjustmentRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    document_no: str
    location_id: uuid.UUID
    reason: StockAdjustmentReason
    status: DocumentStatus
    posted_by: uuid.UUID | None
    posted_at: datetime | None
    cancelled_by: uuid.UUID | None
    cancelled_at: datetime | None
    notes: str | None
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


StockAdjustmentListResponse = Page[StockAdjustmentRead]


class StockAdjustmentFilters(RequestSchema):
    search: str | None = None
    location_id: uuid.UUID | None = None
    reason: StockAdjustmentReason | None = None
    status: DocumentStatus | None = None
    created_at_gte: datetime | None = None
    created_at_lte: datetime | None = None


def stock_adjustment_filters(
    search: Annotated[str | None, Query()] = None,
    location_id: Annotated[uuid.UUID | None, Query()] = None,
    reason: Annotated[StockAdjustmentReason | None, Query()] = None,
    status: Annotated[DocumentStatus | None, Query()] = None,
    created_at_gte: Annotated[str | None, Query()] = None,
    created_at_lte: Annotated[str | None, Query()] = None,
) -> StockAdjustmentFilters:
    from_dt, to_dt = parse_datetime_range(
        created_at_gte,
        created_at_lte,
        from_field="created_at_gte",
        to_field="created_at_lte",
    )
    return build_query_model(
        StockAdjustmentFilters,
        search=search,
        location_id=location_id,
        reason=reason,
        status=status,
        created_at_gte=from_dt,
        created_at_lte=to_dt,
    )


class StockAdjustmentLineRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    stock_adjustment_id: uuid.UUID
    line_no: int
    product_variant_id: uuid.UUID
    variant_unit_id: uuid.UUID
    stock_batch_id: uuid.UUID | None
    quantity: Decimal
    conversion_to_base: Decimal
    quantity_base: Decimal
    unit_cost_base: Decimal | None
    expiry_date: date | None
    manufactured_date: date | None
    lot_number: str | None
    notes: str | None


StockAdjustmentLineListResponse = Page[StockAdjustmentLineRead]


class StockAdjustmentLineFilters(RequestSchema):
    product_variant_id: uuid.UUID | None = None
    stock_batch_id: uuid.UUID | None = None
    variant_unit_id: uuid.UUID | None = None


def stock_adjustment_line_filters(
    product_variant_id: Annotated[uuid.UUID | None, Query()] = None,
    stock_batch_id: Annotated[uuid.UUID | None, Query()] = None,
    variant_unit_id: Annotated[uuid.UUID | None, Query()] = None,
) -> StockAdjustmentLineFilters:
    return build_query_model(
        StockAdjustmentLineFilters,
        product_variant_id=product_variant_id,
        stock_batch_id=stock_batch_id,
        variant_unit_id=variant_unit_id,
    )


class StockAdjustmentLineCreate(LotNumberRequestSchema):
    line_no: int = Field(gt=0)
    product_variant_id: uuid.UUID
    stock_batch_id: uuid.UUID | None = None
    variant_unit_id: uuid.UUID
    quantity: Decimal = Field(max_digits=24, decimal_places=8)
    unit_cost_base: Decimal | None = Field(default=None, gt=0, max_digits=24, decimal_places=8)
    expiry_date: date | None = None
    manufactured_date: date | None = None
    lot_number: str | None = Field(default=None, max_length=120)
    notes: str | None = None

    @model_validator(mode="after")
    def quantity_must_be_non_zero(self) -> "StockAdjustmentLineCreate":
        if self.quantity == 0:
            raise ValueError("quantity must not be zero")
        return self


class StockAdjustmentLineUpdate(LotNumberRequestSchema):
    line_no: int | None = Field(default=None, gt=0)
    product_variant_id: uuid.UUID | None = None
    stock_batch_id: uuid.UUID | None = None
    variant_unit_id: uuid.UUID | None = None
    quantity: Decimal | None = Field(default=None, max_digits=24, decimal_places=8)
    unit_cost_base: Decimal | None = Field(default=None, gt=0, max_digits=24, decimal_places=8)
    expiry_date: date | None = None
    manufactured_date: date | None = None
    lot_number: str | None = Field(default=None, max_length=120)
    notes: str | None = None

    @model_validator(mode="after")
    def quantity_must_be_non_zero(self) -> "StockAdjustmentLineUpdate":
        if self.quantity == 0:
            raise ValueError("quantity must not be zero")
        return self


class StockAdjustmentDetailRead(StockAdjustmentRead):
    lines: list[StockAdjustmentLineRead] = Field(default_factory=list)


class StockAdjustmentCreate(RequestSchema):
    location_id: uuid.UUID
    reason: StockAdjustmentReason
    notes: str | None = None
    lines: list[StockAdjustmentLineCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def _no_duplicate_line_numbers(self) -> "StockAdjustmentCreate":
        line_nos = [line.line_no for line in self.lines]
        if len(line_nos) != len(set(line_nos)):
            raise ValueError("lines must not repeat the same line_no.")
        return self


class StockAdjustmentUpdate(RequestSchema):
    location_id: uuid.UUID | None = None
    reason: StockAdjustmentReason | None = None
    notes: str | None = None
