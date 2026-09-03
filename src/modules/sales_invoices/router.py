import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from src.dependencies import DbSession
from src.exceptions import InvalidToken
from src.modules.auth.dependencies import CurrentUser
from src.modules.auth.exceptions import InactiveUser
from src.modules.rbac.dependencies import require_permission
from src.modules.rbac.exceptions import PermissionDenied
from src.modules.sales_invoices import service
from src.modules.sales_invoices.exceptions import (
    InvalidSalesInvoiceCustomer,
    InvalidSalesInvoiceDiscount,
    InvalidSalesInvoiceLineDiscount,
    InvalidSalesInvoiceLineProduct,
    InvalidSalesInvoiceLineSourceLocation,
    InvalidSalesInvoiceLineUnit,
    InvalidSalesInvoiceLocation,
    InvalidSalesInvoicePriceLevel,
    MissingSalesInvoiceLinePrice,
    MissingSalesInvoicePriceLevel,
    SalesInvoiceDocumentNoConflict,
    SalesInvoiceHasNoLines,
    SalesInvoiceInsufficientStock,
    SalesInvoiceLineCostNotFound,
    SalesInvoiceLineNoConflict,
    SalesInvoiceLineNotFound,
    SalesInvoiceNotCancellable,
    SalesInvoiceNotDraft,
    SalesInvoiceNotFound,
    SalesInvoiceNotPostable,
)
from src.modules.sales_invoices.schemas import (
    SalesInvoiceCreate,
    SalesInvoiceDetailRead,
    SalesInvoiceFilters,
    SalesInvoiceLineCostFilters,
    SalesInvoiceLineCostListResponse,
    SalesInvoiceLineCostRead,
    SalesInvoiceLineCreate,
    SalesInvoiceLineFilters,
    SalesInvoiceLineListResponse,
    SalesInvoiceLineRead,
    SalesInvoiceLineUpdate,
    SalesInvoiceListResponse,
    SalesInvoiceUpdate,
    sales_invoice_filters,
    sales_invoice_line_cost_filters,
    sales_invoice_line_filters,
)
from src.pagination import PaginationParams, pagination_params
from src.query_filters import SortSpec, parse_sort
from src.schemas import error_responses

router = APIRouter(prefix="/sales-invoices", tags=["Sales Invoices"])

INVOICE_SORT_FIELDS = {"document_no", "invoice_date", "status", "total_amount", "created_at", "id"}
INVOICE_DEFAULT_SORT = ("invoice_date", "document_no", "id")
LINE_SORT_FIELDS = {"line_no", "product_variant_id", "id"}
LINE_DEFAULT_SORT = ("line_no", "id")
COST_SORT_FIELDS = {"stock_batch_id", "quantity_base", "total_cost", "id"}
COST_DEFAULT_SORT = ("id",)
AUTH_ERRORS = (InvalidToken, InactiveUser, PermissionDenied)
CREATE_VALIDATION_ERRORS = (
    SalesInvoiceDocumentNoConflict,
    InvalidSalesInvoiceCustomer,
    InvalidSalesInvoicePriceLevel,
    MissingSalesInvoicePriceLevel,
    InvalidSalesInvoiceLocation,
    InvalidSalesInvoiceDiscount,
    InvalidSalesInvoiceLineProduct,
    InvalidSalesInvoiceLineUnit,
    InvalidSalesInvoiceLineSourceLocation,
    MissingSalesInvoiceLinePrice,
    InvalidSalesInvoiceLineDiscount,
)
LINE_VALIDATION_ERRORS = (
    SalesInvoiceLineNoConflict,
    InvalidSalesInvoiceLineProduct,
    InvalidSalesInvoiceLineUnit,
    InvalidSalesInvoiceLineSourceLocation,
    MissingSalesInvoiceLinePrice,
    InvalidSalesInvoiceLineDiscount,
    SalesInvoiceNotDraft,
)
WORKFLOW_ERRORS = (
    SalesInvoiceHasNoLines,
    SalesInvoiceNotPostable,
    SalesInvoiceNotCancellable,
    InvalidSalesInvoiceLineProduct,
    InvalidSalesInvoiceLineSourceLocation,
    SalesInvoiceInsufficientStock,
)


def sales_invoice_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(sort, allowed_fields=INVOICE_SORT_FIELDS, default=INVOICE_DEFAULT_SORT)


def sales_invoice_line_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(sort, allowed_fields=LINE_SORT_FIELDS, default=LINE_DEFAULT_SORT)


def sales_invoice_line_cost_sort(
    sort: Annotated[str | None, Query()] = None,
) -> tuple[SortSpec, ...]:
    return parse_sort(sort, allowed_fields=COST_SORT_FIELDS, default=COST_DEFAULT_SORT)


@router.get(
    "",
    response_model=SalesInvoiceListResponse,
    dependencies=[Depends(require_permission("sales_invoices.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_sales_invoices(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[SalesInvoiceFilters, Depends(sales_invoice_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(sales_invoice_sort)],
):
    return await service.list_sales_invoices(db, current.tenant_id, pagination, filters, sort)


@router.post(
    "",
    response_model=SalesInvoiceDetailRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("sales_invoices.create"))],
    responses=error_responses(*AUTH_ERRORS, *CREATE_VALIDATION_ERRORS),
)
async def create_sales_invoice(
    db: DbSession,
    current: CurrentUser,
    body: SalesInvoiceCreate,
):
    return await service.create_invoice(
        db,
        current.tenant_id,
        body,
        actor_user_id=current.user_id,
    )


@router.get(
    "/{sales_invoice_id}",
    response_model=SalesInvoiceDetailRead,
    dependencies=[Depends(require_permission("sales_invoices.read"))],
    responses=error_responses(*AUTH_ERRORS, SalesInvoiceNotFound),
)
async def get_sales_invoice(
    db: DbSession,
    current: CurrentUser,
    sales_invoice_id: uuid.UUID,
):
    invoice = await service.get_invoice_detail_by_id(db, current.tenant_id, sales_invoice_id)
    if invoice is None:
        raise SalesInvoiceNotFound()
    return invoice


@router.patch(
    "/{sales_invoice_id}",
    response_model=SalesInvoiceDetailRead,
    dependencies=[Depends(require_permission("sales_invoices.update"))],
    responses=error_responses(
        *AUTH_ERRORS,
        SalesInvoiceNotFound,
        SalesInvoiceNotDraft,
        *CREATE_VALIDATION_ERRORS,
    ),
)
async def update_sales_invoice(
    db: DbSession,
    current: CurrentUser,
    sales_invoice_id: uuid.UUID,
    body: SalesInvoiceUpdate,
):
    return await service.update_invoice(
        db,
        current.tenant_id,
        sales_invoice_id,
        body,
        actor_user_id=current.user_id,
    )


@router.delete(
    "/{sales_invoice_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("sales_invoices.delete"))],
    responses=error_responses(
        *AUTH_ERRORS,
        SalesInvoiceNotFound,
        SalesInvoiceNotCancellable,
    ),
)
async def cancel_sales_invoice(
    db: DbSession,
    current: CurrentUser,
    sales_invoice_id: uuid.UUID,
) -> None:
    await service.cancel_invoice(
        db,
        current.tenant_id,
        sales_invoice_id,
        actor_user_id=current.user_id,
    )


@router.post(
    "/{sales_invoice_id}/post",
    response_model=SalesInvoiceDetailRead,
    dependencies=[Depends(require_permission("sales_invoices.update"))],
    responses=error_responses(*AUTH_ERRORS, SalesInvoiceNotFound, *WORKFLOW_ERRORS),
)
async def post_sales_invoice(
    db: DbSession,
    current: CurrentUser,
    sales_invoice_id: uuid.UUID,
):
    return await service.post_invoice(
        db,
        current.tenant_id,
        sales_invoice_id,
        actor_user_id=current.user_id,
    )


@router.get(
    "/{sales_invoice_id}/lines",
    response_model=SalesInvoiceLineListResponse,
    dependencies=[Depends(require_permission("sales_invoices.read"))],
    responses=error_responses(*AUTH_ERRORS, SalesInvoiceNotFound),
)
async def list_sales_invoice_lines(
    db: DbSession,
    current: CurrentUser,
    sales_invoice_id: uuid.UUID,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[SalesInvoiceLineFilters, Depends(sales_invoice_line_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(sales_invoice_line_sort)],
):
    return await service.list_lines(
        db,
        current.tenant_id,
        sales_invoice_id,
        pagination,
        filters,
        sort,
    )


@router.post(
    "/{sales_invoice_id}/lines",
    response_model=SalesInvoiceLineRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("sales_invoices.create"))],
    responses=error_responses(
        *AUTH_ERRORS,
        SalesInvoiceNotFound,
        *LINE_VALIDATION_ERRORS,
    ),
)
async def create_sales_invoice_line(
    db: DbSession,
    current: CurrentUser,
    sales_invoice_id: uuid.UUID,
    body: SalesInvoiceLineCreate,
):
    return await service.create_line(
        db,
        current.tenant_id,
        sales_invoice_id,
        body,
        actor_user_id=current.user_id,
    )


@router.get(
    "/{sales_invoice_id}/lines/{line_id}",
    response_model=SalesInvoiceLineRead,
    dependencies=[Depends(require_permission("sales_invoices.read"))],
    responses=error_responses(*AUTH_ERRORS, SalesInvoiceNotFound, SalesInvoiceLineNotFound),
)
async def get_sales_invoice_line(
    db: DbSession,
    current: CurrentUser,
    sales_invoice_id: uuid.UUID,
    line_id: uuid.UUID,
):
    invoice = await service.get_by_id(db, current.tenant_id, sales_invoice_id)
    if invoice is None:
        raise SalesInvoiceNotFound()
    line = await service.get_line_by_id(db, current.tenant_id, sales_invoice_id, line_id)
    if line is None:
        raise SalesInvoiceLineNotFound()
    return line


@router.patch(
    "/{sales_invoice_id}/lines/{line_id}",
    response_model=SalesInvoiceLineRead,
    dependencies=[Depends(require_permission("sales_invoices.update"))],
    responses=error_responses(
        *AUTH_ERRORS,
        SalesInvoiceNotFound,
        SalesInvoiceLineNotFound,
        *LINE_VALIDATION_ERRORS,
    ),
)
async def update_sales_invoice_line(
    db: DbSession,
    current: CurrentUser,
    sales_invoice_id: uuid.UUID,
    line_id: uuid.UUID,
    body: SalesInvoiceLineUpdate,
):
    return await service.update_line(
        db,
        current.tenant_id,
        sales_invoice_id,
        line_id,
        body,
        actor_user_id=current.user_id,
    )


@router.delete(
    "/{sales_invoice_id}/lines/{line_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("sales_invoices.delete"))],
    responses=error_responses(
        *AUTH_ERRORS,
        SalesInvoiceNotFound,
        SalesInvoiceLineNotFound,
        SalesInvoiceNotDraft,
    ),
)
async def delete_sales_invoice_line(
    db: DbSession,
    current: CurrentUser,
    sales_invoice_id: uuid.UUID,
    line_id: uuid.UUID,
) -> None:
    await service.delete_line(
        db,
        current.tenant_id,
        sales_invoice_id,
        line_id,
        actor_user_id=current.user_id,
    )


@router.get(
    "/{sales_invoice_id}/lines/{line_id}/costs",
    response_model=SalesInvoiceLineCostListResponse,
    dependencies=[Depends(require_permission("sales_invoices.read"))],
    responses=error_responses(*AUTH_ERRORS, SalesInvoiceNotFound, SalesInvoiceLineNotFound),
)
async def list_sales_invoice_line_costs(
    db: DbSession,
    current: CurrentUser,
    sales_invoice_id: uuid.UUID,
    line_id: uuid.UUID,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[SalesInvoiceLineCostFilters, Depends(sales_invoice_line_cost_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(sales_invoice_line_cost_sort)],
):
    return await service.list_line_costs(
        db,
        current.tenant_id,
        sales_invoice_id,
        line_id,
        pagination,
        filters,
        sort,
    )


@router.get(
    "/{sales_invoice_id}/lines/{line_id}/costs/{cost_id}",
    response_model=SalesInvoiceLineCostRead,
    dependencies=[Depends(require_permission("sales_invoices.read"))],
    responses=error_responses(
        *AUTH_ERRORS,
        SalesInvoiceNotFound,
        SalesInvoiceLineNotFound,
        SalesInvoiceLineCostNotFound,
    ),
)
async def get_sales_invoice_line_cost(
    db: DbSession,
    current: CurrentUser,
    sales_invoice_id: uuid.UUID,
    line_id: uuid.UUID,
    cost_id: uuid.UUID,
):
    cost = await service.get_line_cost_by_id(
        db,
        current.tenant_id,
        sales_invoice_id,
        line_id,
        cost_id,
    )
    if cost is None:
        raise SalesInvoiceLineCostNotFound()
    return cost
