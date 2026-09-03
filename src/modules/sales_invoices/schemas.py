import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import Query
from pydantic import Field, model_validator

from src.foundation_enums import DocumentStatus
from src.pagination import Page
from src.query_filters import build_query_model
from src.schemas import RequestSchema, ResponseSchema


class SalesInvoiceRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    document_no: str
    customer_id: uuid.UUID | None
    location_id: uuid.UUID
    price_level_id: uuid.UUID
    invoice_date: date
    status: DocumentStatus
    subtotal_amount: Decimal
    discount_amount: Decimal
    total_amount: Decimal
    paid_amount: Decimal
    balance_amount: Decimal
    total_cost: Decimal
    gross_profit: Decimal
    notes: str | None
    posted_at: datetime | None
    posted_by: uuid.UUID | None
    posted_by_name: str | None = None
    cancelled_at: datetime | None
    cancelled_by: uuid.UUID | None
    reversal_of_id: uuid.UUID | None
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


SalesInvoiceListResponse = Page[SalesInvoiceRead]


class SalesInvoiceFilters(RequestSchema):
    search: str | None = None
    customer_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None
    price_level_id: uuid.UUID | None = None
    status: DocumentStatus | None = None
    invoice_date_gte: date | None = None
    invoice_date_lte: date | None = None


def sales_invoice_filters(
    search: Annotated[str | None, Query()] = None,
    customer_id: Annotated[uuid.UUID | None, Query()] = None,
    location_id: Annotated[uuid.UUID | None, Query()] = None,
    price_level_id: Annotated[uuid.UUID | None, Query()] = None,
    status: Annotated[DocumentStatus | None, Query()] = None,
    invoice_date_gte: Annotated[date | None, Query()] = None,
    invoice_date_lte: Annotated[date | None, Query()] = None,
) -> SalesInvoiceFilters:
    return build_query_model(
        SalesInvoiceFilters,
        search=search,
        customer_id=customer_id,
        location_id=location_id,
        price_level_id=price_level_id,
        status=status,
        invoice_date_gte=invoice_date_gte,
        invoice_date_lte=invoice_date_lte,
    )


class SalesInvoiceLineLocationRead(ResponseSchema):
    id: uuid.UUID
    location_id: uuid.UUID
    quantity: Decimal
    quantity_base: Decimal


class SalesInvoiceLineRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    sales_invoice_id: uuid.UUID
    line_no: int
    product_variant_id: uuid.UUID
    variant_unit_id: uuid.UUID
    source_location_id: uuid.UUID | None
    quantity: Decimal
    conversion_to_base: Decimal
    quantity_base: Decimal
    measured_quantity: Decimal | None
    unit_price: Decimal
    discount_amount: Decimal
    line_total: Decimal
    total_cost: Decimal
    gross_profit: Decimal
    price_rule_id: uuid.UUID | None
    locations: list[SalesInvoiceLineLocationRead] = Field(default_factory=list)


SalesInvoiceLineListResponse = Page[SalesInvoiceLineRead]


class SalesInvoiceLineFilters(RequestSchema):
    product_variant_id: uuid.UUID | None = None
    variant_unit_id: uuid.UUID | None = None
    source_location_id: uuid.UUID | None = None
    price_rule_id: uuid.UUID | None = None


def sales_invoice_line_filters(
    product_variant_id: Annotated[uuid.UUID | None, Query()] = None,
    variant_unit_id: Annotated[uuid.UUID | None, Query()] = None,
    source_location_id: Annotated[uuid.UUID | None, Query()] = None,
    price_rule_id: Annotated[uuid.UUID | None, Query()] = None,
) -> SalesInvoiceLineFilters:
    return build_query_model(
        SalesInvoiceLineFilters,
        product_variant_id=product_variant_id,
        variant_unit_id=variant_unit_id,
        source_location_id=source_location_id,
        price_rule_id=price_rule_id,
    )


class SalesInvoiceLineLocationCreate(RequestSchema):
    location_id: uuid.UUID
    quantity: Decimal = Field(gt=0, max_digits=24, decimal_places=8)


class SalesInvoiceLineCreate(RequestSchema):
    line_no: int = Field(gt=0)
    product_variant_id: uuid.UUID
    variant_unit_id: uuid.UUID
    source_location_id: uuid.UUID | None = None
    locations: list[SalesInvoiceLineLocationCreate] = Field(default_factory=list)
    quantity: Decimal = Field(gt=0, max_digits=24, decimal_places=8)
    measured_quantity: Decimal | None = Field(default=None, gt=0, max_digits=24, decimal_places=8)
    unit_price: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=4)
    discount_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=20, decimal_places=4)


class SalesInvoiceLineUpdate(RequestSchema):
    line_no: int | None = Field(default=None, gt=0)
    product_variant_id: uuid.UUID | None = None
    variant_unit_id: uuid.UUID | None = None
    source_location_id: uuid.UUID | None = None
    locations: list[SalesInvoiceLineLocationCreate] | None = None
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=24, decimal_places=8)
    measured_quantity: Decimal | None = Field(default=None, gt=0, max_digits=24, decimal_places=8)
    unit_price: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=4)
    discount_amount: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=4)


class SalesInvoiceDetailRead(SalesInvoiceRead):
    lines: list[SalesInvoiceLineRead] = Field(default_factory=list)


class SalesInvoiceCreate(RequestSchema):
    customer_id: uuid.UUID | None = None
    location_id: uuid.UUID
    price_level_id: uuid.UUID | None = None
    invoice_date: date
    discount_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=20, decimal_places=4)
    notes: str | None = None
    lines: list[SalesInvoiceLineCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def _no_duplicate_line_numbers(self) -> "SalesInvoiceCreate":
        line_nos = [line.line_no for line in self.lines]
        if len(line_nos) != len(set(line_nos)):
            raise ValueError("lines must not repeat the same line_no.")
        return self


class SalesInvoiceUpdate(RequestSchema):
    customer_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None
    price_level_id: uuid.UUID | None = None
    invoice_date: date | None = None
    discount_amount: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=4)
    notes: str | None = None


class SalesInvoiceLineCostRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    sales_invoice_line_id: uuid.UUID
    stock_batch_id: uuid.UUID
    stock_movement_id: uuid.UUID
    quantity_base: Decimal
    unit_cost_base: Decimal
    total_cost: Decimal


SalesInvoiceLineCostListResponse = Page[SalesInvoiceLineCostRead]


class SalesInvoiceLineCostFilters(RequestSchema):
    stock_batch_id: uuid.UUID | None = None
    stock_movement_id: uuid.UUID | None = None


def sales_invoice_line_cost_filters(
    stock_batch_id: Annotated[uuid.UUID | None, Query()] = None,
    stock_movement_id: Annotated[uuid.UUID | None, Query()] = None,
) -> SalesInvoiceLineCostFilters:
    return build_query_model(
        SalesInvoiceLineCostFilters,
        stock_batch_id=stock_batch_id,
        stock_movement_id=stock_movement_id,
    )
