import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import Query
from pydantic import Field, model_validator

from src.foundation_enums import (
    CustomerLedgerEntryType,
    DocumentStatus,
    PaymentMethod,
    SourceType,
)
from src.pagination import Page
from src.query_filters import build_query_model
from src.schemas import RequestSchema, ResponseSchema


class CustomerPaymentRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    document_no: str
    customer_id: uuid.UUID
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


CustomerPaymentListResponse = Page[CustomerPaymentRead]


class CustomerPaymentFilters(RequestSchema):
    search: str | None = None
    customer_id: uuid.UUID | None = None
    payment_method: PaymentMethod | None = None
    status: DocumentStatus | None = None
    payment_date_gte: date | None = None
    payment_date_lte: date | None = None


def customer_payment_filters(
    search: Annotated[str | None, Query()] = None,
    customer_id: Annotated[uuid.UUID | None, Query()] = None,
    payment_method: Annotated[PaymentMethod | None, Query()] = None,
    status: Annotated[DocumentStatus | None, Query()] = None,
    payment_date_gte: Annotated[date | None, Query()] = None,
    payment_date_lte: Annotated[date | None, Query()] = None,
) -> CustomerPaymentFilters:
    return build_query_model(
        CustomerPaymentFilters,
        search=search,
        customer_id=customer_id,
        payment_method=payment_method,
        status=status,
        payment_date_gte=payment_date_gte,
        payment_date_lte=payment_date_lte,
    )


class CustomerPaymentAllocationRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    customer_payment_id: uuid.UUID
    sales_invoice_id: uuid.UUID
    allocated_amount: Decimal


CustomerPaymentAllocationListResponse = Page[CustomerPaymentAllocationRead]


class CustomerPaymentAllocationFilters(RequestSchema):
    sales_invoice_id: uuid.UUID | None = None


def customer_payment_allocation_filters(
    sales_invoice_id: Annotated[uuid.UUID | None, Query()] = None,
) -> CustomerPaymentAllocationFilters:
    return build_query_model(
        CustomerPaymentAllocationFilters,
        sales_invoice_id=sales_invoice_id,
    )


class CustomerPaymentAllocationCreate(RequestSchema):
    sales_invoice_id: uuid.UUID
    allocated_amount: Decimal = Field(gt=0, max_digits=20, decimal_places=4)


class CustomerPaymentAllocationUpdate(RequestSchema):
    sales_invoice_id: uuid.UUID | None = None
    allocated_amount: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=20,
        decimal_places=4,
    )


class CustomerPaymentDetailRead(CustomerPaymentRead):
    allocations: list[CustomerPaymentAllocationRead] = Field(default_factory=list)


class CustomerPaymentCreate(RequestSchema):
    customer_id: uuid.UUID
    payment_date: date
    payment_method: PaymentMethod = PaymentMethod.CASH
    amount: Decimal = Field(gt=0, max_digits=20, decimal_places=4)
    notes: str | None = None
    allocations: list[CustomerPaymentAllocationCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def _no_duplicate_allocation_invoices(self) -> "CustomerPaymentCreate":
        invoice_ids = [allocation.sales_invoice_id for allocation in self.allocations]
        if len(invoice_ids) != len(set(invoice_ids)):
            raise ValueError("allocations must not repeat the same sales_invoice_id.")
        return self


class CustomerPaymentUpdate(RequestSchema):
    customer_id: uuid.UUID | None = None
    payment_date: date | None = None
    payment_method: PaymentMethod | None = None
    amount: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=4)
    notes: str | None = None


class CustomerPaymentReverse(RequestSchema):
    reason: str = Field(min_length=1, max_length=2000)


class CustomerLedgerEntryRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    customer_id: uuid.UUID
    entry_type: CustomerLedgerEntryType
    debit_amount: Decimal
    credit_amount: Decimal
    balance_effect: Decimal
    source_type: SourceType
    source_id: uuid.UUID
    posted_at: datetime
    posted_by: uuid.UUID


CustomerLedgerEntryListResponse = Page[CustomerLedgerEntryRead]


class CustomerLedgerEntryFilters(RequestSchema):
    customer_id: uuid.UUID | None = None
    entry_type: CustomerLedgerEntryType | None = None
    source_type: SourceType | None = None
    source_id: uuid.UUID | None = None
    posted_at_gte: datetime | None = None
    posted_at_lte: datetime | None = None


def customer_ledger_entry_filters(
    customer_id: Annotated[uuid.UUID | None, Query()] = None,
    entry_type: Annotated[CustomerLedgerEntryType | None, Query()] = None,
    source_type: Annotated[SourceType | None, Query()] = None,
    source_id: Annotated[uuid.UUID | None, Query()] = None,
    posted_at_gte: Annotated[datetime | None, Query()] = None,
    posted_at_lte: Annotated[datetime | None, Query()] = None,
) -> CustomerLedgerEntryFilters:
    return build_query_model(
        CustomerLedgerEntryFilters,
        customer_id=customer_id,
        entry_type=entry_type,
        source_type=source_type,
        source_id=source_id,
        posted_at_gte=posted_at_gte,
        posted_at_lte=posted_at_lte,
    )


class CustomerBalanceRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    customer_id: uuid.UUID
    balance_amount: Decimal
    updated_at: datetime


CustomerBalanceListResponse = Page[CustomerBalanceRead]


class CustomerBalanceFilters(RequestSchema):
    customer_id: uuid.UUID | None = None


def customer_balance_filters(
    customer_id: Annotated[uuid.UUID | None, Query()] = None,
) -> CustomerBalanceFilters:
    return build_query_model(CustomerBalanceFilters, customer_id=customer_id)


class CustomerBalanceReconciliationEntry(ResponseSchema):
    customer_id: uuid.UUID
    cached_balance: Decimal
    ledger_balance: Decimal
    delta: Decimal
