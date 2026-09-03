import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status

from src.dependencies import DbSession
from src.exceptions import InvalidToken
from src.modules.auth.dependencies import CurrentUser
from src.modules.auth.exceptions import InactiveUser
from src.modules.rbac.dependencies import require_permission
from src.modules.rbac.exceptions import PermissionDenied
from src.modules.supplier_payments import service
from src.modules.supplier_payments.exceptions import (
    InvalidSupplierPaymentAllocationInvoice,
    InvalidSupplierPaymentSupplier,
    SupplierBalanceNotFound,
    SupplierLedgerEntryNotFound,
    SupplierPaymentAllocationInvoiceConflict,
    SupplierPaymentAllocationNotEditable,
    SupplierPaymentAllocationNotFound,
    SupplierPaymentDocumentNoConflict,
    SupplierPaymentInvoiceOverpaid,
    SupplierPaymentNotCancellable,
    SupplierPaymentNotDraft,
    SupplierPaymentNotFound,
    SupplierPaymentNotPostable,
    SupplierPaymentNotReversible,
    SupplierPaymentOverAllocated,
)
from src.modules.supplier_payments.schemas import (
    SupplierBalanceFilters,
    SupplierBalanceListResponse,
    SupplierBalanceRead,
    SupplierBalanceReconciliationEntry,
    SupplierLedgerEntryFilters,
    SupplierLedgerEntryListResponse,
    SupplierLedgerEntryRead,
    SupplierPaymentAllocationCreate,
    SupplierPaymentAllocationFilters,
    SupplierPaymentAllocationListResponse,
    SupplierPaymentAllocationRead,
    SupplierPaymentAllocationUpdate,
    SupplierPaymentCreate,
    SupplierPaymentDetailRead,
    SupplierPaymentFilters,
    SupplierPaymentListResponse,
    SupplierPaymentRead,
    SupplierPaymentReverse,
    SupplierPaymentUpdate,
    supplier_balance_filters,
    supplier_ledger_entry_filters,
    supplier_payment_allocation_filters,
    supplier_payment_filters,
)
from src.pagination import PaginationParams, pagination_params
from src.query_filters import SortSpec, parse_sort
from src.schemas import error_responses

router = APIRouter(tags=["Supplier Payments"])

PAYMENT_SORT_FIELDS = {"document_no", "payment_date", "status", "amount", "created_at", "id"}
PAYMENT_DEFAULT_SORT = ("payment_date", "document_no", "id")
ALLOCATION_SORT_FIELDS = {"purchase_invoice_id", "allocated_amount", "id"}
ALLOCATION_DEFAULT_SORT = ("purchase_invoice_id", "id")
LEDGER_SORT_FIELDS = {"posted_at", "supplier_id", "entry_type", "id"}
LEDGER_DEFAULT_SORT = ("posted_at", "id")
BALANCE_SORT_FIELDS = {"supplier_id", "balance_amount", "updated_at", "id"}
BALANCE_DEFAULT_SORT = ("supplier_id", "id")
AUTH_ERRORS = (InvalidToken, InactiveUser, PermissionDenied)
CREATE_VALIDATION_ERRORS = (
    SupplierPaymentDocumentNoConflict,
    InvalidSupplierPaymentSupplier,
    InvalidSupplierPaymentAllocationInvoice,
    SupplierPaymentOverAllocated,
    SupplierPaymentInvoiceOverpaid,
)
ALLOCATION_VALIDATION_ERRORS = (
    SupplierPaymentAllocationNotEditable,
    SupplierPaymentAllocationInvoiceConflict,
    InvalidSupplierPaymentAllocationInvoice,
    SupplierPaymentOverAllocated,
    SupplierPaymentInvoiceOverpaid,
)
WORKFLOW_ERRORS = (
    SupplierPaymentNotPostable,
    SupplierPaymentNotCancellable,
    SupplierPaymentOverAllocated,
    SupplierPaymentInvoiceOverpaid,
    InvalidSupplierPaymentSupplier,
    InvalidSupplierPaymentAllocationInvoice,
)
REVERSAL_ERRORS = (SupplierPaymentNotReversible,)


def supplier_payment_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(sort, allowed_fields=PAYMENT_SORT_FIELDS, default=PAYMENT_DEFAULT_SORT)


def supplier_payment_allocation_sort(
    sort: Annotated[str | None, Query()] = None,
) -> tuple[SortSpec, ...]:
    return parse_sort(
        sort,
        allowed_fields=ALLOCATION_SORT_FIELDS,
        default=ALLOCATION_DEFAULT_SORT,
    )


def supplier_ledger_entry_sort(
    sort: Annotated[str | None, Query()] = None,
) -> tuple[SortSpec, ...]:
    return parse_sort(sort, allowed_fields=LEDGER_SORT_FIELDS, default=LEDGER_DEFAULT_SORT)


def supplier_balance_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(sort, allowed_fields=BALANCE_SORT_FIELDS, default=BALANCE_DEFAULT_SORT)


@router.get(
    "/supplier-payments",
    response_model=SupplierPaymentListResponse,
    dependencies=[Depends(require_permission("supplier_payments.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_supplier_payments(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[SupplierPaymentFilters, Depends(supplier_payment_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(supplier_payment_sort)],
):
    return await service.list_supplier_payments(db, current.tenant_id, pagination, filters, sort)


@router.post(
    "/supplier-payments",
    response_model=SupplierPaymentDetailRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("supplier_payments.create"))],
    responses=error_responses(*AUTH_ERRORS, *CREATE_VALIDATION_ERRORS),
)
async def create_supplier_payment(
    db: DbSession,
    current: CurrentUser,
    body: SupplierPaymentCreate,
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
    "/supplier-payments/{supplier_payment_id}",
    response_model=SupplierPaymentDetailRead,
    dependencies=[Depends(require_permission("supplier_payments.read"))],
    responses=error_responses(*AUTH_ERRORS, SupplierPaymentNotFound),
)
async def get_supplier_payment(
    db: DbSession,
    current: CurrentUser,
    supplier_payment_id: uuid.UUID,
):
    payment = await service.get_payment_detail_by_id(db, current.tenant_id, supplier_payment_id)
    if payment is None:
        raise SupplierPaymentNotFound()
    return payment


@router.patch(
    "/supplier-payments/{supplier_payment_id}",
    response_model=SupplierPaymentRead,
    dependencies=[Depends(require_permission("supplier_payments.update"))],
    responses=error_responses(
        *AUTH_ERRORS,
        SupplierPaymentNotFound,
        SupplierPaymentNotDraft,
        *CREATE_VALIDATION_ERRORS,
    ),
)
async def update_supplier_payment(
    db: DbSession,
    current: CurrentUser,
    supplier_payment_id: uuid.UUID,
    body: SupplierPaymentUpdate,
):
    return await service.update_payment(
        db,
        current.tenant_id,
        supplier_payment_id,
        body,
        actor_user_id=current.user_id,
    )


@router.delete(
    "/supplier-payments/{supplier_payment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("supplier_payments.delete"))],
    responses=error_responses(*AUTH_ERRORS, SupplierPaymentNotFound, *WORKFLOW_ERRORS),
)
async def cancel_supplier_payment(
    db: DbSession,
    current: CurrentUser,
    supplier_payment_id: uuid.UUID,
) -> None:
    await service.cancel_payment(
        db,
        current.tenant_id,
        supplier_payment_id,
        actor_user_id=current.user_id,
    )


@router.post(
    "/supplier-payments/{supplier_payment_id}/post",
    response_model=SupplierPaymentDetailRead,
    dependencies=[Depends(require_permission("supplier_payments.update"))],
    responses=error_responses(*AUTH_ERRORS, SupplierPaymentNotFound, *WORKFLOW_ERRORS),
)
async def post_supplier_payment(
    db: DbSession,
    current: CurrentUser,
    supplier_payment_id: uuid.UUID,
):
    return await service.post_payment(
        db,
        current.tenant_id,
        supplier_payment_id,
        actor_user_id=current.user_id,
    )


@router.post(
    "/supplier-payments/{supplier_payment_id}/reverse",
    response_model=SupplierPaymentDetailRead,
    dependencies=[Depends(require_permission("supplier_payments.reverse"))],
    responses=error_responses(*AUTH_ERRORS, SupplierPaymentNotFound, *REVERSAL_ERRORS),
)
async def reverse_supplier_payment(
    db: DbSession,
    current: CurrentUser,
    supplier_payment_id: uuid.UUID,
    body: SupplierPaymentReverse,
):
    return await service.reverse_payment(
        db,
        current.tenant_id,
        supplier_payment_id,
        body.reason,
        actor_user_id=current.user_id,
    )


@router.get(
    "/supplier-payments/{supplier_payment_id}/allocations",
    response_model=SupplierPaymentAllocationListResponse,
    dependencies=[Depends(require_permission("supplier_payments.read"))],
    responses=error_responses(*AUTH_ERRORS, SupplierPaymentNotFound),
)
async def list_supplier_payment_allocations(
    db: DbSession,
    current: CurrentUser,
    supplier_payment_id: uuid.UUID,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[
        SupplierPaymentAllocationFilters,
        Depends(supplier_payment_allocation_filters),
    ],
    sort: Annotated[tuple[SortSpec, ...], Depends(supplier_payment_allocation_sort)],
):
    return await service.list_allocations(
        db,
        current.tenant_id,
        supplier_payment_id,
        pagination,
        filters,
        sort,
    )


@router.post(
    "/supplier-payments/{supplier_payment_id}/allocations",
    response_model=SupplierPaymentAllocationRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("supplier_payments.create"))],
    responses=error_responses(
        *AUTH_ERRORS,
        SupplierPaymentNotFound,
        *ALLOCATION_VALIDATION_ERRORS,
    ),
)
async def create_supplier_payment_allocation(
    db: DbSession,
    current: CurrentUser,
    supplier_payment_id: uuid.UUID,
    body: SupplierPaymentAllocationCreate,
):
    return await service.create_allocation(
        db,
        current.tenant_id,
        supplier_payment_id,
        body,
        actor_user_id=current.user_id,
    )


@router.get(
    "/supplier-payments/{supplier_payment_id}/allocations/{allocation_id}",
    response_model=SupplierPaymentAllocationRead,
    dependencies=[Depends(require_permission("supplier_payments.read"))],
    responses=error_responses(
        *AUTH_ERRORS,
        SupplierPaymentNotFound,
        SupplierPaymentAllocationNotFound,
    ),
)
async def get_supplier_payment_allocation(
    db: DbSession,
    current: CurrentUser,
    supplier_payment_id: uuid.UUID,
    allocation_id: uuid.UUID,
):
    payment = await service.get_by_id(db, current.tenant_id, supplier_payment_id)
    if payment is None:
        raise SupplierPaymentNotFound()
    allocation = await service.get_allocation_by_id(
        db,
        current.tenant_id,
        supplier_payment_id,
        allocation_id,
    )
    if allocation is None:
        raise SupplierPaymentAllocationNotFound()
    return allocation


@router.patch(
    "/supplier-payments/{supplier_payment_id}/allocations/{allocation_id}",
    response_model=SupplierPaymentAllocationRead,
    dependencies=[Depends(require_permission("supplier_payments.update"))],
    responses=error_responses(
        *AUTH_ERRORS,
        SupplierPaymentNotFound,
        SupplierPaymentAllocationNotFound,
        *ALLOCATION_VALIDATION_ERRORS,
    ),
)
async def update_supplier_payment_allocation(
    db: DbSession,
    current: CurrentUser,
    supplier_payment_id: uuid.UUID,
    allocation_id: uuid.UUID,
    body: SupplierPaymentAllocationUpdate,
):
    return await service.update_allocation(
        db,
        current.tenant_id,
        supplier_payment_id,
        allocation_id,
        body,
        actor_user_id=current.user_id,
    )


@router.delete(
    "/supplier-payments/{supplier_payment_id}/allocations/{allocation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("supplier_payments.delete"))],
    responses=error_responses(
        *AUTH_ERRORS,
        SupplierPaymentNotFound,
        SupplierPaymentAllocationNotFound,
        SupplierPaymentNotDraft,
    ),
)
async def delete_supplier_payment_allocation(
    db: DbSession,
    current: CurrentUser,
    supplier_payment_id: uuid.UUID,
    allocation_id: uuid.UUID,
) -> None:
    await service.delete_allocation(
        db,
        current.tenant_id,
        supplier_payment_id,
        allocation_id,
        actor_user_id=current.user_id,
    )


@router.get(
    "/supplier-ledger-entries",
    response_model=SupplierLedgerEntryListResponse,
    dependencies=[Depends(require_permission("supplier_payments.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_supplier_ledger_entries(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[SupplierLedgerEntryFilters, Depends(supplier_ledger_entry_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(supplier_ledger_entry_sort)],
):
    return await service.list_ledger_entries(db, current.tenant_id, pagination, filters, sort)


@router.get(
    "/supplier-ledger-entries/{entry_id}",
    response_model=SupplierLedgerEntryRead,
    dependencies=[Depends(require_permission("supplier_payments.read"))],
    responses=error_responses(*AUTH_ERRORS, SupplierLedgerEntryNotFound),
)
async def get_supplier_ledger_entry(
    db: DbSession,
    current: CurrentUser,
    entry_id: uuid.UUID,
):
    entry = await service.get_ledger_entry_by_id(db, current.tenant_id, entry_id)
    if entry is None:
        raise SupplierLedgerEntryNotFound()
    return entry


@router.get(
    "/supplier-balances",
    response_model=SupplierBalanceListResponse,
    dependencies=[Depends(require_permission("supplier_payments.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_supplier_balances(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[SupplierBalanceFilters, Depends(supplier_balance_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(supplier_balance_sort)],
):
    return await service.list_balances(db, current.tenant_id, pagination, filters, sort)


@router.get(
    "/supplier-balances/reconciliation",
    response_model=list[SupplierBalanceReconciliationEntry],
    dependencies=[Depends(require_permission("supplier_payments.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def get_supplier_balance_reconciliation(
    db: DbSession,
    current: CurrentUser,
    supplier_id: Annotated[uuid.UUID | None, Query()] = None,
):
    return await service.get_balance_reconciliation(
        db,
        current.tenant_id,
        supplier_id=supplier_id,
    )


@router.get(
    "/supplier-balances/{balance_id}",
    response_model=SupplierBalanceRead,
    dependencies=[Depends(require_permission("supplier_payments.read"))],
    responses=error_responses(*AUTH_ERRORS, SupplierBalanceNotFound),
)
async def get_supplier_balance(
    db: DbSession,
    current: CurrentUser,
    balance_id: uuid.UUID,
):
    balance = await service.get_balance_by_id(db, current.tenant_id, balance_id)
    if balance is None:
        raise SupplierBalanceNotFound()
    return balance
