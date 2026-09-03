import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import Query
from pydantic import Field, field_validator, model_validator

from src.foundation_enums import (
    DocumentStatus,
    LandedCostAllocationMethod,
    PurchaseLandedCostType,
)
from src.modules.document_numbers.service import is_generated_lot_number
from src.pagination import Page
from src.query_filters import build_query_model
from src.schemas import RequestSchema, ResponseSchema


class LotNumberRequestSchema(RequestSchema):
    @field_validator("lot_number", check_fields=False)
    @classmethod
    def _manual_lot_must_not_use_generated_format(cls, value: str | None) -> str | None:
        if value is not None and is_generated_lot_number(value):
            raise ValueError("LOT-YYYYMM-NNNNNN is reserved for server-generated lot numbers.")
        return value


class PurchaseInvoiceRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    document_no: str
    supplier_id: uuid.UUID
    invoice_date: date
    supplier_invoice_no: str | None
    status: DocumentStatus
    subtotal_amount: Decimal
    landed_cost_amount: Decimal
    total_amount: Decimal
    paid_amount: Decimal
    balance_amount: Decimal
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


PurchaseInvoiceListResponse = Page[PurchaseInvoiceRead]


class PurchaseInvoiceFilters(RequestSchema):
    search: str | None = None
    supplier_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None
    status: DocumentStatus | None = None
    invoice_date_gte: date | None = None
    invoice_date_lte: date | None = None


def purchase_invoice_filters(
    search: Annotated[str | None, Query()] = None,
    supplier_id: Annotated[uuid.UUID | None, Query()] = None,
    location_id: Annotated[uuid.UUID | None, Query()] = None,
    status: Annotated[DocumentStatus | None, Query()] = None,
    invoice_date_gte: Annotated[date | None, Query()] = None,
    invoice_date_lte: Annotated[date | None, Query()] = None,
) -> PurchaseInvoiceFilters:
    return build_query_model(
        PurchaseInvoiceFilters,
        search=search,
        supplier_id=supplier_id,
        location_id=location_id,
        status=status,
        invoice_date_gte=invoice_date_gte,
        invoice_date_lte=invoice_date_lte,
    )


class PurchaseInvoiceLineRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    purchase_invoice_id: uuid.UUID
    line_no: int
    product_variant_id: uuid.UUID
    variant_unit_id: uuid.UUID
    location_id: uuid.UUID
    quantity: Decimal
    conversion_to_base: Decimal
    quantity_base: Decimal
    measured_quantity: Decimal | None
    unit_cost: Decimal
    line_amount: Decimal
    allocated_landed_cost: Decimal
    total_line_cost: Decimal
    unit_cost_base: Decimal
    expiry_date: date | None
    manufactured_date: date | None
    lot_number: str | None
    created_stock_batch_id: uuid.UUID | None


PurchaseInvoiceLineListResponse = Page[PurchaseInvoiceLineRead]


class PurchaseInvoiceLineFilters(RequestSchema):
    product_variant_id: uuid.UUID | None = None
    variant_unit_id: uuid.UUID | None = None


def purchase_invoice_line_filters(
    product_variant_id: Annotated[uuid.UUID | None, Query()] = None,
    variant_unit_id: Annotated[uuid.UUID | None, Query()] = None,
) -> PurchaseInvoiceLineFilters:
    return build_query_model(
        PurchaseInvoiceLineFilters,
        product_variant_id=product_variant_id,
        variant_unit_id=variant_unit_id,
    )


class PurchaseInvoiceLineCreate(LotNumberRequestSchema):
    line_no: int = Field(gt=0)
    product_variant_id: uuid.UUID
    variant_unit_id: uuid.UUID
    location_id: uuid.UUID
    quantity: Decimal = Field(gt=0, max_digits=24, decimal_places=8)
    measured_quantity: Decimal | None = Field(default=None, gt=0, max_digits=24, decimal_places=8)
    unit_cost: Decimal = Field(gt=0, max_digits=20, decimal_places=4)
    expiry_date: date | None = None
    manufactured_date: date | None = None
    lot_number: str | None = Field(default=None, max_length=120)


class PurchaseInvoiceLineUpdate(LotNumberRequestSchema):
    line_no: int | None = Field(default=None, gt=0)
    product_variant_id: uuid.UUID | None = None
    variant_unit_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=24, decimal_places=8)
    measured_quantity: Decimal | None = Field(default=None, gt=0, max_digits=24, decimal_places=8)
    unit_cost: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=4)
    expiry_date: date | None = None
    manufactured_date: date | None = None
    lot_number: str | None = Field(default=None, max_length=120)


class PurchaseLandedCostRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    purchase_invoice_id: uuid.UUID
    cost_type: PurchaseLandedCostType
    description: str | None
    amount: Decimal
    allocation_method: LandedCostAllocationMethod
    created_at: datetime


PurchaseLandedCostListResponse = Page[PurchaseLandedCostRead]


class PurchaseLandedCostFilters(RequestSchema):
    cost_type: PurchaseLandedCostType | None = None
    allocation_method: LandedCostAllocationMethod | None = None


def purchase_landed_cost_filters(
    cost_type: Annotated[PurchaseLandedCostType | None, Query()] = None,
    allocation_method: Annotated[LandedCostAllocationMethod | None, Query()] = None,
) -> PurchaseLandedCostFilters:
    return build_query_model(
        PurchaseLandedCostFilters,
        cost_type=cost_type,
        allocation_method=allocation_method,
    )


class PurchaseLandedCostCreate(RequestSchema):
    cost_type: PurchaseLandedCostType
    description: str | None = None
    amount: Decimal = Field(gt=0, max_digits=20, decimal_places=4)
    allocation_method: LandedCostAllocationMethod = LandedCostAllocationMethod.BY_VALUE


class PurchaseLandedCostUpdate(RequestSchema):
    cost_type: PurchaseLandedCostType | None = None
    description: str | None = None
    amount: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=4)
    allocation_method: LandedCostAllocationMethod | None = None


class PurchaseInvoiceDetailRead(PurchaseInvoiceRead):
    lines: list[PurchaseInvoiceLineRead] = Field(default_factory=list)
    landed_costs: list[PurchaseLandedCostRead] = Field(default_factory=list)


class PurchaseInvoiceCreate(RequestSchema):
    supplier_id: uuid.UUID
    invoice_date: date
    supplier_invoice_no: str | None = Field(default=None, max_length=120)
    notes: str | None = None
    lines: list[PurchaseInvoiceLineCreate] = Field(default_factory=list)
    landed_costs: list[PurchaseLandedCostCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def _no_duplicate_line_numbers(self) -> "PurchaseInvoiceCreate":
        line_nos = [line.line_no for line in self.lines]
        if len(line_nos) != len(set(line_nos)):
            raise ValueError("lines must not repeat the same line_no.")
        return self


class PurchaseInvoiceUpdate(RequestSchema):
    supplier_id: uuid.UUID | None = None
    invoice_date: date | None = None
    supplier_invoice_no: str | None = Field(default=None, max_length=120)
    notes: str | None = None
