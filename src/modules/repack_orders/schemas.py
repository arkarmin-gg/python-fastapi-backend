import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import Query
from pydantic import Field, field_validator, model_validator

from src.foundation_enums import DocumentStatus
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


class RepackOrderRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    document_no: str
    location_id: uuid.UUID
    status: DocumentStatus
    performed_by: uuid.UUID | None
    total_input_cost: Decimal
    total_output_cost: Decimal
    waste_cost: Decimal
    total_input_quantity_base: Decimal
    total_output_quantity_base: Decimal
    posted_by: uuid.UUID | None
    posted_at: datetime | None
    cancelled_by: uuid.UUID | None
    cancelled_at: datetime | None
    reversal_of_id: uuid.UUID | None
    notes: str | None
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


RepackOrderListResponse = Page[RepackOrderRead]


class RepackOrderFilters(RequestSchema):
    search: str | None = None
    location_id: uuid.UUID | None = None
    status: DocumentStatus | None = None
    performed_by: uuid.UUID | None = None
    created_at_gte: datetime | None = None
    created_at_lte: datetime | None = None


def repack_order_filters(
    search: Annotated[str | None, Query()] = None,
    location_id: Annotated[uuid.UUID | None, Query()] = None,
    status: Annotated[DocumentStatus | None, Query()] = None,
    performed_by: Annotated[uuid.UUID | None, Query()] = None,
    created_at_gte: Annotated[str | None, Query()] = None,
    created_at_lte: Annotated[str | None, Query()] = None,
) -> RepackOrderFilters:
    from_dt, to_dt = parse_datetime_range(
        created_at_gte,
        created_at_lte,
        from_field="created_at_gte",
        to_field="created_at_lte",
    )
    return build_query_model(
        RepackOrderFilters,
        search=search,
        location_id=location_id,
        status=status,
        performed_by=performed_by,
        created_at_gte=from_dt,
        created_at_lte=to_dt,
    )


class RepackOrderInputRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    repack_order_id: uuid.UUID
    line_no: int
    product_variant_id: uuid.UUID
    variant_unit_id: uuid.UUID
    stock_batch_id: uuid.UUID
    quantity: Decimal
    conversion_to_base: Decimal
    quantity_base: Decimal
    unit_cost_base: Decimal
    total_cost: Decimal


RepackOrderInputListResponse = Page[RepackOrderInputRead]


class RepackOrderInputFilters(RequestSchema):
    product_variant_id: uuid.UUID | None = None
    stock_batch_id: uuid.UUID | None = None
    variant_unit_id: uuid.UUID | None = None


def repack_order_input_filters(
    product_variant_id: Annotated[uuid.UUID | None, Query()] = None,
    stock_batch_id: Annotated[uuid.UUID | None, Query()] = None,
    variant_unit_id: Annotated[uuid.UUID | None, Query()] = None,
) -> RepackOrderInputFilters:
    return build_query_model(
        RepackOrderInputFilters,
        product_variant_id=product_variant_id,
        stock_batch_id=stock_batch_id,
        variant_unit_id=variant_unit_id,
    )


class RepackOrderInputCreate(RequestSchema):
    line_no: int = Field(gt=0)
    product_variant_id: uuid.UUID
    stock_batch_id: uuid.UUID
    variant_unit_id: uuid.UUID
    quantity: Decimal = Field(gt=0, max_digits=24, decimal_places=8)


class RepackOrderInputUpdate(RequestSchema):
    line_no: int | None = Field(default=None, gt=0)
    product_variant_id: uuid.UUID | None = None
    stock_batch_id: uuid.UUID | None = None
    variant_unit_id: uuid.UUID | None = None
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=24, decimal_places=8)


class RepackOrderOutputRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    repack_order_id: uuid.UUID
    line_no: int
    product_variant_id: uuid.UUID
    variant_unit_id: uuid.UUID
    quantity: Decimal
    conversion_to_base: Decimal
    quantity_base: Decimal
    allocated_cost: Decimal
    unit_cost_base: Decimal
    expiry_date: date | None
    lot_number: str | None
    created_stock_batch_id: uuid.UUID | None


RepackOrderOutputListResponse = Page[RepackOrderOutputRead]


class RepackOrderOutputFilters(RequestSchema):
    product_variant_id: uuid.UUID | None = None
    variant_unit_id: uuid.UUID | None = None
    created_stock_batch_id: uuid.UUID | None = None


def repack_order_output_filters(
    product_variant_id: Annotated[uuid.UUID | None, Query()] = None,
    variant_unit_id: Annotated[uuid.UUID | None, Query()] = None,
    created_stock_batch_id: Annotated[uuid.UUID | None, Query()] = None,
) -> RepackOrderOutputFilters:
    return build_query_model(
        RepackOrderOutputFilters,
        product_variant_id=product_variant_id,
        variant_unit_id=variant_unit_id,
        created_stock_batch_id=created_stock_batch_id,
    )


class RepackOrderOutputCreate(LotNumberRequestSchema):
    line_no: int = Field(gt=0)
    product_variant_id: uuid.UUID
    variant_unit_id: uuid.UUID
    quantity: Decimal = Field(gt=0, max_digits=24, decimal_places=8)
    allocated_cost: Decimal = Field(ge=0, max_digits=20, decimal_places=4)
    expiry_date: date | None = None
    lot_number: str | None = Field(default=None, max_length=120)


class RepackOrderOutputUpdate(LotNumberRequestSchema):
    line_no: int | None = Field(default=None, gt=0)
    product_variant_id: uuid.UUID | None = None
    variant_unit_id: uuid.UUID | None = None
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=24, decimal_places=8)
    allocated_cost: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=4)
    expiry_date: date | None = None
    lot_number: str | None = Field(default=None, max_length=120)


class RepackOrderDetailRead(RepackOrderRead):
    inputs: list[RepackOrderInputRead] = Field(default_factory=list)
    outputs: list[RepackOrderOutputRead] = Field(default_factory=list)


class RepackOrderCreate(RequestSchema):
    location_id: uuid.UUID
    performed_by: uuid.UUID | None = None
    notes: str | None = None
    inputs: list[RepackOrderInputCreate] = Field(default_factory=list)
    outputs: list[RepackOrderOutputCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def _no_duplicate_line_numbers(self) -> "RepackOrderCreate":
        input_line_nos = [line.line_no for line in self.inputs]
        if len(input_line_nos) != len(set(input_line_nos)):
            raise ValueError("inputs must not repeat the same line_no.")
        output_line_nos = [line.line_no for line in self.outputs]
        if len(output_line_nos) != len(set(output_line_nos)):
            raise ValueError("outputs must not repeat the same line_no.")
        return self


class RepackOrderUpdate(RequestSchema):
    location_id: uuid.UUID | None = None
    performed_by: uuid.UUID | None = None
    notes: str | None = None
