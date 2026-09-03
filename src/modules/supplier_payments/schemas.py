import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import Query
from pydantic import Field, model_validator

from src.foundation_enums import (
    DocumentStatus,
    PaymentMethod,
    SourceType,
    SupplierLedgerEntryType,
)
from src.pagination import Page
from src.query_filters import build_query_model
from src.schemas import RequestSchema, ResponseSchema


class SupplierPaymentRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    document_no: str
    supplier_id: uuid.UUID
    payment_date: date
    payment_method: PaymentMethod
    amount: Decimal
    status: DocumentStatus
    notes: str | None
    posted_at: datetime | None
    posted_by: uuid.UUID | None
    cancelled_at: datetime | None
    cancelled_by: uuid.UUID | None
    reversed_at: datetime | None
    reversed_by: uuid.UUID | None
    reversal_reason: str | None
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


SupplierPaymentListResponse = Page[SupplierPaymentRead]


class SupplierPaymentFilters(RequestSchema):
    search: str | None = None
    supplier_id: uuid.UUID | None = None
    payment_method: PaymentMethod | None = None
    status: DocumentStatus | None = None
    payment_date_gte: date | None = None
    payment_date_lte: date | None = None


def supplier_payment_filters(
    search: Annotated[str | None, Query()] = None,
    supplier_id: Annotated[uuid.UUID | None, Query()] = None,
    payment_method: Annotated[PaymentMethod | None, Query()] = None,
    status: Annotated[DocumentStatus | None, Query()] = None,
    payment_date_gte: Annotated[date | None, Query()] = None,
    payment_date_lte: Annotated[date | None, Query()] = None,
) -> SupplierPaymentFilters:
    return build_query_model(
        SupplierPaymentFilters,
        search=search,
        supplier_id=supplier_id,
        payment_method=payment_method,
        status=status,
        payment_date_gte=payment_date_gte,
        payment_date_lte=payment_date_lte,
    )


class SupplierPaymentAllocationRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    supplier_payment_id: uuid.UUID
    purchase_invoice_id: uuid.UUID
    allocated_amount: Decimal


SupplierPaymentAllocationListResponse = Page[SupplierPaymentAllocationRead]


class SupplierPaymentAllocationFilters(RequestSchema):
    purchase_invoice_id: uuid.UUID | None = None


def supplier_payment_allocation_filters(
    purchase_invoice_id: Annotated[uuid.UUID | None, Query()] = None,
) -> SupplierPaymentAllocationFilters:
    return build_query_model(
        SupplierPaymentAllocationFilters,
        purchase_invoice_id=purchase_invoice_id,
    )


class SupplierPaymentAllocationCreate(RequestSchema):
    purchase_invoice_id: uuid.UUID
    allocated_amount: Decimal = Field(gt=0, max_digits=20, decimal_places=4)


class SupplierPaymentAllocationUpdate(RequestSchema):
    purchase_invoice_id: uuid.UUID | None = None
    allocated_amount: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=20,
        decimal_places=4,
    )


class SupplierPaymentDetailRead(SupplierPaymentRead):
    allocations: list[SupplierPaymentAllocationRead] = Field(default_factory=list)


class SupplierPaymentCreate(RequestSchema):
    supplier_id: uuid.UUID
    payment_date: date
    payment_method: PaymentMethod = PaymentMethod.CASH
    amount: Decimal = Field(gt=0, max_digits=20, decimal_places=4)
    notes: str | None = None
    allocations: list[SupplierPaymentAllocationCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def _no_duplicate_allocation_invoices(self) -> "SupplierPaymentCreate":
        invoice_ids = [allocation.purchase_invoice_id for allocation in self.allocations]
        if len(invoice_ids) != len(set(invoice_ids)):
            raise ValueError("allocations must not repeat the same purchase_invoice_id.")
        return self


class SupplierPaymentUpdate(RequestSchema):
    supplier_id: uuid.UUID | None = None
    payment_date: date | None = None
    payment_method: PaymentMethod | None = None
    amount: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=4)
    notes: str | None = None


class SupplierPaymentReverse(RequestSchema):
    reason: str = Field(min_length=1, max_length=2000)


class SupplierLedgerEntryRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    supplier_id: uuid.UUID
    entry_type: SupplierLedgerEntryType
    debit_amount: Decimal
    credit_amount: Decimal
    balance_effect: Decimal
    source_type: SourceType
    source_id: uuid.UUID
    posted_at: datetime
    posted_by: uuid.UUID


SupplierLedgerEntryListResponse = Page[SupplierLedgerEntryRead]


class SupplierLedgerEntryFilters(RequestSchema):
    supplier_id: uuid.UUID | None = None
    entry_type: SupplierLedgerEntryType | None = None
    source_type: SourceType | None = None
    source_id: uuid.UUID | None = None
    posted_at_gte: datetime | None = None
    posted_at_lte: datetime | None = None


def supplier_ledger_entry_filters(
    supplier_id: Annotated[uuid.UUID | None, Query()] = None,
    entry_type: Annotated[SupplierLedgerEntryType | None, Query()] = None,
    source_type: Annotated[SourceType | None, Query()] = None,
    source_id: Annotated[uuid.UUID | None, Query()] = None,
    posted_at_gte: Annotated[datetime | None, Query()] = None,
    posted_at_lte: Annotated[datetime | None, Query()] = None,
) -> SupplierLedgerEntryFilters:
    return build_query_model(
        SupplierLedgerEntryFilters,
        supplier_id=supplier_id,
        entry_type=entry_type,
        source_type=source_type,
        source_id=source_id,
        posted_at_gte=posted_at_gte,
        posted_at_lte=posted_at_lte,
    )


class SupplierBalanceRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    supplier_id: uuid.UUID
    balance_amount: Decimal
    updated_at: datetime


SupplierBalanceListResponse = Page[SupplierBalanceRead]


class SupplierBalanceFilters(RequestSchema):
    supplier_id: uuid.UUID | None = None


def supplier_balance_filters(
    supplier_id: Annotated[uuid.UUID | None, Query()] = None,
) -> SupplierBalanceFilters:
    return build_query_model(SupplierBalanceFilters, supplier_id=supplier_id)


class SupplierBalanceReconciliationEntry(ResponseSchema):
    supplier_id: uuid.UUID
    cached_balance: Decimal
    ledger_balance: Decimal
    delta: Decimal
