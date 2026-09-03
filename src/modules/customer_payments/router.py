import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status

from src.dependencies import DbSession
from src.exceptions import InvalidToken
from src.modules.auth.dependencies import CurrentUser
from src.modules.auth.exceptions import InactiveUser
from src.modules.customer_payments import service
from src.modules.customer_payments.exceptions import (
    CustomerBalanceNotFound,
    CustomerLedgerEntryNotFound,
    CustomerPaymentAllocationInvoiceConflict,
    CustomerPaymentAllocationNotEditable,
    CustomerPaymentAllocationNotFound,
    CustomerPaymentDocumentNoConflict,
    CustomerPaymentInvoiceOverpaid,
    CustomerPaymentNotCancellable,
    CustomerPaymentNotDraft,
    CustomerPaymentNotFound,
    CustomerPaymentNotPostable,
    CustomerPaymentNotReversible,
    CustomerPaymentOverAllocated,
    InvalidCustomerPaymentAllocationInvoice,
    InvalidCustomerPaymentCustomer,
)
from src.modules.customer_payments.schemas import (
    CustomerBalanceFilters,
    CustomerBalanceListResponse,
    CustomerBalanceRead,
    CustomerBalanceReconciliationEntry,
    CustomerLedgerEntryFilters,
    CustomerLedgerEntryListResponse,
    CustomerLedgerEntryRead,
    CustomerPaymentAllocationCreate,
    CustomerPaymentAllocationFilters,
    CustomerPaymentAllocationListResponse,
    CustomerPaymentAllocationRead,
    CustomerPaymentAllocationUpdate,
    CustomerPaymentCreate,
    CustomerPaymentDetailRead,
    CustomerPaymentFilters,
    CustomerPaymentListResponse,
    CustomerPaymentRead,
    CustomerPaymentReverse,
    CustomerPaymentUpdate,
    customer_balance_filters,
    customer_ledger_entry_filters,
    customer_payment_allocation_filters,
    customer_payment_filters,
)
from src.modules.rbac.dependencies import require_permission
from src.modules.rbac.exceptions import PermissionDenied
from src.pagination import PaginationParams, pagination_params
from src.query_filters import SortSpec, parse_sort
from src.schemas import error_responses

router = APIRouter(tags=["Customer Payments"])

PAYMENT_SORT_FIELDS = {"document_no", "payment_date", "status", "amount", "created_at", "id"}
PAYMENT_DEFAULT_SORT = ("payment_date", "document_no", "id")
ALLOCATION_SORT_FIELDS = {"sales_invoice_id", "allocated_amount", "id"}
ALLOCATION_DEFAULT_SORT = ("sales_invoice_id", "id")
LEDGER_SORT_FIELDS = {"posted_at", "customer_id", "entry_type", "id"}
LEDGER_DEFAULT_SORT = ("posted_at", "id")
BALANCE_SORT_FIELDS = {"customer_id", "balance_amount", "updated_at", "id"}
BALANCE_DEFAULT_SORT = ("customer_id", "id")
AUTH_ERRORS = (InvalidToken, InactiveUser, PermissionDenied)
CREATE_VALIDATION_ERRORS = (
    CustomerPaymentDocumentNoConflict,
    InvalidCustomerPaymentCustomer,
    InvalidCustomerPaymentAllocationInvoice,
    CustomerPaymentOverAllocated,
    CustomerPaymentInvoiceOverpaid,
)
ALLOCATION_VALIDATION_ERRORS = (
    CustomerPaymentAllocationNotEditable,
    CustomerPaymentAllocationInvoiceConflict,
    InvalidCustomerPaymentAllocationInvoice,
    CustomerPaymentOverAllocated,
    CustomerPaymentInvoiceOverpaid,
)
WORKFLOW_ERRORS = (
    CustomerPaymentNotPostable,
    CustomerPaymentNotCancellable,
    CustomerPaymentOverAllocated,
    CustomerPaymentInvoiceOverpaid,
    InvalidCustomerPaymentCustomer,
    InvalidCustomerPaymentAllocationInvoice,
)
REVERSAL_ERRORS = (CustomerPaymentNotReversible,)


def customer_payment_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(sort, allowed_fields=PAYMENT_SORT_FIELDS, default=PAYMENT_DEFAULT_SORT)


def customer_payment_allocation_sort(
    sort: Annotated[str | None, Query()] = None,
) -> tuple[SortSpec, ...]:
    return parse_sort(
        sort,
        allowed_fields=ALLOCATION_SORT_FIELDS,
        default=ALLOCATION_DEFAULT_SORT,
    )


def customer_ledger_entry_sort(
    sort: Annotated[str | None, Query()] = None,
) -> tuple[SortSpec, ...]:
    return parse_sort(sort, allowed_fields=LEDGER_SORT_FIELDS, default=LEDGER_DEFAULT_SORT)


def customer_balance_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(sort, allowed_fields=BALANCE_SORT_FIELDS, default=BALANCE_DEFAULT_SORT)


@router.get(
    "/customer-payments",
    response_model=CustomerPaymentListResponse,
    dependencies=[Depends(require_permission("customer_payments.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_customer_payments(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[CustomerPaymentFilters, Depends(customer_payment_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(customer_payment_sort)],
):
    return await service.list_customer_payments(db, current.tenant_id, pagination, filters, sort)


@router.post(
    "/customer-payments",
    response_model=CustomerPaymentDetailRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("customer_payments.create"))],
    responses=error_responses(*AUTH_ERRORS, *CREATE_VALIDATION_ERRORS),
)
async def create_customer_payment(
    db: DbSession,
    current: CurrentUser,
    body: CustomerPaymentCreate,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    return await service.create_payment(
        db,
        current.tenant_id,
        body,
        actor_user_id=current.user_id,
        idempotency_key=idempotency_key,
    )


@router.get(
    "/customer-payments/{customer_payment_id}",
    response_model=CustomerPaymentDetailRead,
    dependencies=[Depends(require_permission("customer_payments.read"))],
    responses=error_responses(*AUTH_ERRORS, CustomerPaymentNotFound),
)
async def get_customer_payment(
    db: DbSession,
    current: CurrentUser,
    customer_payment_id: uuid.UUID,
):
    payment = await service.get_payment_detail_by_id(db, current.tenant_id, customer_payment_id)
    if payment is None:
        raise CustomerPaymentNotFound()
    return payment


@router.patch(
    "/customer-payments/{customer_payment_id}",
    response_model=CustomerPaymentRead,
    dependencies=[Depends(require_permission("customer_payments.update"))],
    responses=error_responses(
        *AUTH_ERRORS,
        CustomerPaymentNotFound,
        CustomerPaymentNotDraft,
        *CREATE_VALIDATION_ERRORS,
    ),
)
async def update_customer_payment(
    db: DbSession,
    current: CurrentUser,
    customer_payment_id: uuid.UUID,
    body: CustomerPaymentUpdate,
):
    return await service.update_payment(
        db,
        current.tenant_id,
        customer_payment_id,
        body,
        actor_user_id=current.user_id,
    )


@router.delete(
    "/customer-payments/{customer_payment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("customer_payments.delete"))],
    responses=error_responses(*AUTH_ERRORS, CustomerPaymentNotFound, *WORKFLOW_ERRORS),
)
async def cancel_customer_payment(
    db: DbSession,
    current: CurrentUser,
    customer_payment_id: uuid.UUID,
) -> None:
    await service.cancel_payment(
        db,
        current.tenant_id,
        customer_payment_id,
        actor_user_id=current.user_id,
    )


@router.post(
    "/customer-payments/{customer_payment_id}/post",
    response_model=CustomerPaymentDetailRead,
    dependencies=[Depends(require_permission("customer_payments.update"))],
    responses=error_responses(*AUTH_ERRORS, CustomerPaymentNotFound, *WORKFLOW_ERRORS),
)
async def post_customer_payment(
    db: DbSession,
    current: CurrentUser,
    customer_payment_id: uuid.UUID,
):
    return await service.post_payment(
        db,
        current.tenant_id,
        customer_payment_id,
        actor_user_id=current.user_id,
    )


@router.post(
    "/customer-payments/{customer_payment_id}/reverse",
    response_model=CustomerPaymentDetailRead,
    dependencies=[Depends(require_permission("customer_payments.reverse"))],
    responses=error_responses(*AUTH_ERRORS, CustomerPaymentNotFound, *REVERSAL_ERRORS),
)
async def reverse_customer_payment(
    db: DbSession,
    current: CurrentUser,
    customer_payment_id: uuid.UUID,
    body: CustomerPaymentReverse,
):
    return await service.reverse_payment(
        db,
        current.tenant_id,
        customer_payment_id,
        body.reason,
        actor_user_id=current.user_id,
    )


@router.get(
    "/customer-payments/{customer_payment_id}/allocations",
    response_model=CustomerPaymentAllocationListResponse,
    dependencies=[Depends(require_permission("customer_payments.read"))],
    responses=error_responses(*AUTH_ERRORS, CustomerPaymentNotFound),
)
async def list_customer_payment_allocations(
    db: DbSession,
    current: CurrentUser,
    customer_payment_id: uuid.UUID,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[
        CustomerPaymentAllocationFilters,
        Depends(customer_payment_allocation_filters),
    ],
    sort: Annotated[tuple[SortSpec, ...], Depends(customer_payment_allocation_sort)],
):
    return await service.list_allocations(
        db,
        current.tenant_id,
        customer_payment_id,
        pagination,
        filters,
        sort,
    )


@router.post(
    "/customer-payments/{customer_payment_id}/allocations",
    response_model=CustomerPaymentAllocationRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("customer_payments.create"))],
    responses=error_responses(
        *AUTH_ERRORS,
        CustomerPaymentNotFound,
        *ALLOCATION_VALIDATION_ERRORS,
    ),
)
async def create_customer_payment_allocation(
    db: DbSession,
    current: CurrentUser,
    customer_payment_id: uuid.UUID,
    body: CustomerPaymentAllocationCreate,
):
    return await service.create_allocation(
        db,
        current.tenant_id,
        customer_payment_id,
        body,
        actor_user_id=current.user_id,
    )


@router.get(
    "/customer-payments/{customer_payment_id}/allocations/{allocation_id}",
    response_model=CustomerPaymentAllocationRead,
    dependencies=[Depends(require_permission("customer_payments.read"))],
    responses=error_responses(
        *AUTH_ERRORS,
        CustomerPaymentNotFound,
        CustomerPaymentAllocationNotFound,
    ),
)
async def get_customer_payment_allocation(
    db: DbSession,
    current: CurrentUser,
    customer_payment_id: uuid.UUID,
    allocation_id: uuid.UUID,
):
    payment = await service.get_by_id(db, current.tenant_id, customer_payment_id)
    if payment is None:
        raise CustomerPaymentNotFound()
    allocation = await service.get_allocation_by_id(
        db,
        current.tenant_id,
        customer_payment_id,
        allocation_id,
    )
    if allocation is None:
        raise CustomerPaymentAllocationNotFound()
    return allocation


@router.patch(
    "/customer-payments/{customer_payment_id}/allocations/{allocation_id}",
    response_model=CustomerPaymentAllocationRead,
    dependencies=[Depends(require_permission("customer_payments.update"))],
    responses=error_responses(
        *AUTH_ERRORS,
        CustomerPaymentNotFound,
        CustomerPaymentAllocationNotFound,
        *ALLOCATION_VALIDATION_ERRORS,
    ),
)
async def update_customer_payment_allocation(
    db: DbSession,
    current: CurrentUser,
    customer_payment_id: uuid.UUID,
    allocation_id: uuid.UUID,
    body: CustomerPaymentAllocationUpdate,
):
    return await service.update_allocation(
        db,
        current.tenant_id,
        customer_payment_id,
        allocation_id,
        body,
        actor_user_id=current.user_id,
    )


@router.delete(
    "/customer-payments/{customer_payment_id}/allocations/{allocation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("customer_payments.delete"))],
    responses=error_responses(
        *AUTH_ERRORS,
        CustomerPaymentNotFound,
        CustomerPaymentAllocationNotFound,
        CustomerPaymentNotDraft,
    ),
)
async def delete_customer_payment_allocation(
    db: DbSession,
    current: CurrentUser,
    customer_payment_id: uuid.UUID,
    allocation_id: uuid.UUID,
) -> None:
    await service.delete_allocation(
        db,
        current.tenant_id,
        customer_payment_id,
        allocation_id,
        actor_user_id=current.user_id,
    )


@router.get(
    "/customer-ledger-entries",
    response_model=CustomerLedgerEntryListResponse,
    dependencies=[Depends(require_permission("customer_payments.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_customer_ledger_entries(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[CustomerLedgerEntryFilters, Depends(customer_ledger_entry_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(customer_ledger_entry_sort)],
):
    return await service.list_ledger_entries(db, current.tenant_id, pagination, filters, sort)


@router.get(
    "/customer-ledger-entries/{entry_id}",
    response_model=CustomerLedgerEntryRead,
    dependencies=[Depends(require_permission("customer_payments.read"))],
    responses=error_responses(*AUTH_ERRORS, CustomerLedgerEntryNotFound),
)
async def get_customer_ledger_entry(
    db: DbSession,
    current: CurrentUser,
    entry_id: uuid.UUID,
):
    entry = await service.get_ledger_entry_by_id(db, current.tenant_id, entry_id)
    if entry is None:
        raise CustomerLedgerEntryNotFound()
    return entry


@router.get(
    "/customer-balances",
    response_model=CustomerBalanceListResponse,
    dependencies=[Depends(require_permission("customer_payments.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_customer_balances(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[CustomerBalanceFilters, Depends(customer_balance_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(customer_balance_sort)],
):
    return await service.list_balances(db, current.tenant_id, pagination, filters, sort)


@router.get(
    "/customer-balances/reconciliation",
    response_model=list[CustomerBalanceReconciliationEntry],
    dependencies=[Depends(require_permission("customer_payments.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def get_customer_balance_reconciliation(
    db: DbSession,
    current: CurrentUser,
    customer_id: Annotated[uuid.UUID | None, Query()] = None,
):
    return await service.get_balance_reconciliation(
        db,
        current.tenant_id,
        customer_id=customer_id,
    )


@router.get(
    "/customer-balances/{balance_id}",
    response_model=CustomerBalanceRead,
    dependencies=[Depends(require_permission("customer_payments.read"))],
    responses=error_responses(*AUTH_ERRORS, CustomerBalanceNotFound),
)
async def get_customer_balance(
    db: DbSession,
    current: CurrentUser,
    balance_id: uuid.UUID,
):
    balance = await service.get_balance_by_id(db, current.tenant_id, balance_id)
    if balance is None:
        raise CustomerBalanceNotFound()
    return balance
