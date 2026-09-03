import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from src.dependencies import DbSession
from src.exceptions import InvalidToken
from src.modules.auth.dependencies import CurrentUser
from src.modules.auth.exceptions import InactiveUser
from src.modules.purchase_invoices import service
from src.modules.purchase_invoices.exceptions import (
    InvalidPurchaseInvoiceLineProduct,
    InvalidPurchaseInvoiceLineUnit,
    InvalidPurchaseInvoiceLocation,
    InvalidPurchaseInvoiceSupplier,
    InvalidPurchaseLandedCostAllocation,
    PurchaseInvoiceDocumentNoConflict,
    PurchaseInvoiceHasNoLines,
    PurchaseInvoiceLineMissingExpiryDate,
    PurchaseInvoiceLineMissingLotNumber,
    PurchaseInvoiceLineNoConflict,
    PurchaseInvoiceLineNotFound,
    PurchaseInvoiceLineProductNotInventoryTracked,
    PurchaseInvoiceNotCancellable,
    PurchaseInvoiceNotDraft,
    PurchaseInvoiceNotFound,
    PurchaseInvoiceNotPostable,
    PurchaseLandedCostNotFound,
)
from src.modules.purchase_invoices.schemas import (
    PurchaseInvoiceCreate,
    PurchaseInvoiceDetailRead,
    PurchaseInvoiceFilters,
    PurchaseInvoiceLineCreate,
    PurchaseInvoiceLineFilters,
    PurchaseInvoiceLineListResponse,
    PurchaseInvoiceLineRead,
    PurchaseInvoiceLineUpdate,
    PurchaseInvoiceListResponse,
    PurchaseInvoiceUpdate,
    PurchaseLandedCostCreate,
    PurchaseLandedCostFilters,
    PurchaseLandedCostListResponse,
    PurchaseLandedCostRead,
    PurchaseLandedCostUpdate,
    purchase_invoice_filters,
    purchase_invoice_line_filters,
    purchase_landed_cost_filters,
)
from src.modules.rbac.dependencies import require_permission
from src.modules.rbac.exceptions import PermissionDenied
from src.pagination import PaginationParams, pagination_params
from src.query_filters import SortSpec, parse_sort
from src.schemas import error_responses

router = APIRouter(prefix="/purchase-invoices", tags=["Purchase Invoices"])

INVOICE_SORT_FIELDS = {"document_no", "invoice_date", "status", "total_amount", "created_at", "id"}
INVOICE_DEFAULT_SORT = ("invoice_date", "document_no", "id")
LINE_SORT_FIELDS = {"line_no", "product_variant_id", "variant_unit_id", "id"}
LINE_DEFAULT_SORT = ("line_no", "id")
LANDED_COST_SORT_FIELDS = {"cost_type", "amount", "created_at", "id"}
LANDED_COST_DEFAULT_SORT = ("created_at", "id")
AUTH_ERRORS = (InvalidToken, InactiveUser, PermissionDenied)
CREATE_VALIDATION_ERRORS = (
    PurchaseInvoiceDocumentNoConflict,
    InvalidPurchaseInvoiceSupplier,
    InvalidPurchaseInvoiceLocation,
    InvalidPurchaseInvoiceLineProduct,
    InvalidPurchaseInvoiceLineUnit,
    InvalidPurchaseLandedCostAllocation,
    PurchaseInvoiceLineProductNotInventoryTracked,
    PurchaseInvoiceLineMissingLotNumber,
    PurchaseInvoiceLineMissingExpiryDate,
)
LINE_VALIDATION_ERRORS = (
    PurchaseInvoiceLineNoConflict,
    InvalidPurchaseInvoiceLineProduct,
    InvalidPurchaseInvoiceLineUnit,
    PurchaseInvoiceNotDraft,
)
LANDED_COST_VALIDATION_ERRORS = (
    InvalidPurchaseLandedCostAllocation,
    PurchaseInvoiceNotDraft,
)
WORKFLOW_ERRORS = (
    PurchaseInvoiceHasNoLines,
    PurchaseInvoiceNotPostable,
    PurchaseInvoiceNotCancellable,
    PurchaseInvoiceLineProductNotInventoryTracked,
    PurchaseInvoiceLineMissingLotNumber,
    PurchaseInvoiceLineMissingExpiryDate,
)


def purchase_invoice_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(sort, allowed_fields=INVOICE_SORT_FIELDS, default=INVOICE_DEFAULT_SORT)


def purchase_invoice_line_sort(
    sort: Annotated[str | None, Query()] = None,
) -> tuple[SortSpec, ...]:
    return parse_sort(sort, allowed_fields=LINE_SORT_FIELDS, default=LINE_DEFAULT_SORT)


def purchase_landed_cost_sort(
    sort: Annotated[str | None, Query()] = None,
) -> tuple[SortSpec, ...]:
    return parse_sort(
        sort,
        allowed_fields=LANDED_COST_SORT_FIELDS,
        default=LANDED_COST_DEFAULT_SORT,
    )


@router.get(
    "",
    response_model=PurchaseInvoiceListResponse,
    dependencies=[Depends(require_permission("purchase_invoices.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_purchase_invoices(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[PurchaseInvoiceFilters, Depends(purchase_invoice_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(purchase_invoice_sort)],
):
    return await service.list_purchase_invoices(db, current.tenant_id, pagination, filters, sort)


@router.post(
    "",
    response_model=PurchaseInvoiceDetailRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("purchase_invoices.create"))],
    responses=error_responses(*AUTH_ERRORS, *CREATE_VALIDATION_ERRORS),
)
async def create_purchase_invoice(
    db: DbSession,
    current: CurrentUser,
    body: PurchaseInvoiceCreate,
):
    return await service.create_invoice(
        db,
        current.tenant_id,
        body,
        actor_user_id=current.user_id,
    )


@router.get(
    "/{purchase_invoice_id}",
    response_model=PurchaseInvoiceDetailRead,
    dependencies=[Depends(require_permission("purchase_invoices.read"))],
    responses=error_responses(*AUTH_ERRORS, PurchaseInvoiceNotFound),
)
async def get_purchase_invoice(
    db: DbSession,
    current: CurrentUser,
    purchase_invoice_id: uuid.UUID,
):
    invoice = await service.get_invoice_detail_by_id(db, current.tenant_id, purchase_invoice_id)
    if invoice is None:
        raise PurchaseInvoiceNotFound()
    return invoice


@router.patch(
    "/{purchase_invoice_id}",
    response_model=PurchaseInvoiceDetailRead,
    dependencies=[Depends(require_permission("purchase_invoices.update"))],
    responses=error_responses(
        *AUTH_ERRORS,
        PurchaseInvoiceNotFound,
        PurchaseInvoiceNotDraft,
        *CREATE_VALIDATION_ERRORS,
    ),
)
async def update_purchase_invoice(
    db: DbSession,
    current: CurrentUser,
    purchase_invoice_id: uuid.UUID,
    body: PurchaseInvoiceUpdate,
):
    return await service.update_invoice(
        db,
        current.tenant_id,
        purchase_invoice_id,
        body,
        actor_user_id=current.user_id,
    )


@router.delete(
    "/{purchase_invoice_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("purchase_invoices.delete"))],
    responses=error_responses(
        *AUTH_ERRORS,
        PurchaseInvoiceNotFound,
        PurchaseInvoiceNotCancellable,
    ),
)
async def cancel_purchase_invoice(
    db: DbSession,
    current: CurrentUser,
    purchase_invoice_id: uuid.UUID,
) -> None:
    await service.cancel_invoice(
        db,
        current.tenant_id,
        purchase_invoice_id,
        actor_user_id=current.user_id,
    )


@router.post(
    "/{purchase_invoice_id}/post",
    response_model=PurchaseInvoiceDetailRead,
    dependencies=[Depends(require_permission("purchase_invoices.update"))],
    responses=error_responses(*AUTH_ERRORS, PurchaseInvoiceNotFound, *WORKFLOW_ERRORS),
)
async def post_purchase_invoice(
    db: DbSession,
    current: CurrentUser,
    purchase_invoice_id: uuid.UUID,
):
    return await service.post_invoice(
        db,
        current.tenant_id,
        purchase_invoice_id,
        actor_user_id=current.user_id,
    )


@router.get(
    "/{purchase_invoice_id}/lines",
    response_model=PurchaseInvoiceLineListResponse,
    dependencies=[Depends(require_permission("purchase_invoices.read"))],
    responses=error_responses(*AUTH_ERRORS, PurchaseInvoiceNotFound),
)
async def list_purchase_invoice_lines(
    db: DbSession,
    current: CurrentUser,
    purchase_invoice_id: uuid.UUID,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[PurchaseInvoiceLineFilters, Depends(purchase_invoice_line_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(purchase_invoice_line_sort)],
):
    return await service.list_lines(
        db,
        current.tenant_id,
        purchase_invoice_id,
        pagination,
        filters,
        sort,
    )


@router.post(
    "/{purchase_invoice_id}/lines",
    response_model=PurchaseInvoiceLineRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("purchase_invoices.create"))],
    responses=error_responses(
        *AUTH_ERRORS,
        PurchaseInvoiceNotFound,
        *LINE_VALIDATION_ERRORS,
    ),
)
async def create_purchase_invoice_line(
    db: DbSession,
    current: CurrentUser,
    purchase_invoice_id: uuid.UUID,
    body: PurchaseInvoiceLineCreate,
):
    return await service.create_line(
        db,
        current.tenant_id,
        purchase_invoice_id,
        body,
        actor_user_id=current.user_id,
    )


@router.get(
    "/{purchase_invoice_id}/lines/{line_id}",
    response_model=PurchaseInvoiceLineRead,
    dependencies=[Depends(require_permission("purchase_invoices.read"))],
    responses=error_responses(*AUTH_ERRORS, PurchaseInvoiceNotFound, PurchaseInvoiceLineNotFound),
)
async def get_purchase_invoice_line(
    db: DbSession,
    current: CurrentUser,
    purchase_invoice_id: uuid.UUID,
    line_id: uuid.UUID,
):
    invoice = await service.get_by_id(db, current.tenant_id, purchase_invoice_id)
    if invoice is None:
        raise PurchaseInvoiceNotFound()
    line = await service.get_line_by_id(db, current.tenant_id, purchase_invoice_id, line_id)
    if line is None:
        raise PurchaseInvoiceLineNotFound()
    return line


@router.patch(
    "/{purchase_invoice_id}/lines/{line_id}",
    response_model=PurchaseInvoiceLineRead,
    dependencies=[Depends(require_permission("purchase_invoices.update"))],
    responses=error_responses(
        *AUTH_ERRORS,
        PurchaseInvoiceNotFound,
        PurchaseInvoiceLineNotFound,
        *LINE_VALIDATION_ERRORS,
    ),
)
async def update_purchase_invoice_line(
    db: DbSession,
    current: CurrentUser,
    purchase_invoice_id: uuid.UUID,
    line_id: uuid.UUID,
    body: PurchaseInvoiceLineUpdate,
):
    return await service.update_line(
        db,
        current.tenant_id,
        purchase_invoice_id,
        line_id,
        body,
        actor_user_id=current.user_id,
    )


@router.delete(
    "/{purchase_invoice_id}/lines/{line_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("purchase_invoices.delete"))],
    responses=error_responses(
        *AUTH_ERRORS,
        PurchaseInvoiceNotFound,
        PurchaseInvoiceLineNotFound,
        PurchaseInvoiceNotDraft,
    ),
)
async def delete_purchase_invoice_line(
    db: DbSession,
    current: CurrentUser,
    purchase_invoice_id: uuid.UUID,
    line_id: uuid.UUID,
) -> None:
    await service.delete_line(
        db,
        current.tenant_id,
        purchase_invoice_id,
        line_id,
        actor_user_id=current.user_id,
    )


@router.get(
    "/{purchase_invoice_id}/landed-costs",
    response_model=PurchaseLandedCostListResponse,
    dependencies=[Depends(require_permission("purchase_invoices.read"))],
    responses=error_responses(*AUTH_ERRORS, PurchaseInvoiceNotFound),
)
async def list_purchase_landed_costs(
    db: DbSession,
    current: CurrentUser,
    purchase_invoice_id: uuid.UUID,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[PurchaseLandedCostFilters, Depends(purchase_landed_cost_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(purchase_landed_cost_sort)],
):
    return await service.list_landed_costs(
        db,
        current.tenant_id,
        purchase_invoice_id,
        pagination,
        filters,
        sort,
    )


@router.post(
    "/{purchase_invoice_id}/landed-costs",
    response_model=PurchaseLandedCostRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("purchase_invoices.create"))],
    responses=error_responses(
        *AUTH_ERRORS,
        PurchaseInvoiceNotFound,
        *LANDED_COST_VALIDATION_ERRORS,
    ),
)
async def create_purchase_landed_cost(
    db: DbSession,
    current: CurrentUser,
    purchase_invoice_id: uuid.UUID,
    body: PurchaseLandedCostCreate,
):
    return await service.create_landed_cost(
        db,
        current.tenant_id,
        purchase_invoice_id,
        body,
        actor_user_id=current.user_id,
    )


@router.get(
    "/{purchase_invoice_id}/landed-costs/{cost_id}",
    response_model=PurchaseLandedCostRead,
    dependencies=[Depends(require_permission("purchase_invoices.read"))],
    responses=error_responses(*AUTH_ERRORS, PurchaseInvoiceNotFound, PurchaseLandedCostNotFound),
)
async def get_purchase_landed_cost(
    db: DbSession,
    current: CurrentUser,
    purchase_invoice_id: uuid.UUID,
    cost_id: uuid.UUID,
):
    invoice = await service.get_by_id(db, current.tenant_id, purchase_invoice_id)
    if invoice is None:
        raise PurchaseInvoiceNotFound()
    landed_cost = await service.get_landed_cost_by_id(
        db,
        current.tenant_id,
        purchase_invoice_id,
        cost_id,
    )
    if landed_cost is None:
        raise PurchaseLandedCostNotFound()
    return landed_cost


@router.patch(
    "/{purchase_invoice_id}/landed-costs/{cost_id}",
    response_model=PurchaseLandedCostRead,
    dependencies=[Depends(require_permission("purchase_invoices.update"))],
    responses=error_responses(
        *AUTH_ERRORS,
        PurchaseInvoiceNotFound,
        PurchaseLandedCostNotFound,
        *LANDED_COST_VALIDATION_ERRORS,
    ),
)
async def update_purchase_landed_cost(
    db: DbSession,
    current: CurrentUser,
    purchase_invoice_id: uuid.UUID,
    cost_id: uuid.UUID,
    body: PurchaseLandedCostUpdate,
):
    return await service.update_landed_cost(
        db,
        current.tenant_id,
        purchase_invoice_id,
        cost_id,
        body,
        actor_user_id=current.user_id,
    )


@router.delete(
    "/{purchase_invoice_id}/landed-costs/{cost_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("purchase_invoices.delete"))],
    responses=error_responses(
        *AUTH_ERRORS,
        PurchaseInvoiceNotFound,
        PurchaseLandedCostNotFound,
        PurchaseInvoiceNotDraft,
    ),
)
async def delete_purchase_landed_cost(
    db: DbSession,
    current: CurrentUser,
    purchase_invoice_id: uuid.UUID,
    cost_id: uuid.UUID,
) -> None:
    await service.delete_landed_cost(
        db,
        current.tenant_id,
        purchase_invoice_id,
        cost_id,
        actor_user_id=current.user_id,
    )
