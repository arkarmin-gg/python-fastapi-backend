import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from src.dependencies import DbSession
from src.exceptions import InvalidToken
from src.modules.auth.dependencies import CurrentUser
from src.modules.auth.exceptions import InactiveUser
from src.modules.rbac.dependencies import require_permission
from src.modules.rbac.exceptions import PermissionDenied
from src.modules.stock_adjustments import service
from src.modules.stock_adjustments.exceptions import (
    InvalidStockAdjustmentLineBatch,
    InvalidStockAdjustmentLineProduct,
    InvalidStockAdjustmentLineUnit,
    InvalidStockAdjustmentLocation,
    StockAdjustmentDocumentNoConflict,
    StockAdjustmentHasNoLines,
    StockAdjustmentLineBatchRequired,
    StockAdjustmentLineCostRequired,
    StockAdjustmentLineNoConflict,
    StockAdjustmentLineNotFound,
    StockAdjustmentNegativeBalance,
    StockAdjustmentNotCancellable,
    StockAdjustmentNotDraft,
    StockAdjustmentNotFound,
    StockAdjustmentNotPostable,
)
from src.modules.stock_adjustments.schemas import (
    StockAdjustmentCreate,
    StockAdjustmentDetailRead,
    StockAdjustmentFilters,
    StockAdjustmentLineCreate,
    StockAdjustmentLineFilters,
    StockAdjustmentLineListResponse,
    StockAdjustmentLineRead,
    StockAdjustmentLineUpdate,
    StockAdjustmentListResponse,
    StockAdjustmentUpdate,
    stock_adjustment_filters,
    stock_adjustment_line_filters,
)
from src.pagination import PaginationParams, pagination_params
from src.query_filters import SortSpec, parse_sort
from src.schemas import error_responses

router = APIRouter(prefix="/stock-adjustments", tags=["Stock Adjustments"])

ADJUSTMENT_SORT_FIELDS = {"document_no", "reason", "status", "created_at", "id"}
ADJUSTMENT_DEFAULT_SORT = ("document_no", "id")
LINE_SORT_FIELDS = {"line_no", "product_variant_id", "stock_batch_id", "variant_unit_id", "id"}
LINE_DEFAULT_SORT = ("line_no", "id")
AUTH_ERRORS = (InvalidToken, InactiveUser, PermissionDenied)
CREATE_VALIDATION_ERRORS = (
    StockAdjustmentDocumentNoConflict,
    InvalidStockAdjustmentLocation,
    InvalidStockAdjustmentLineProduct,
    InvalidStockAdjustmentLineUnit,
    InvalidStockAdjustmentLineBatch,
    StockAdjustmentLineBatchRequired,
    StockAdjustmentLineCostRequired,
)
LINE_VALIDATION_ERRORS = (
    StockAdjustmentLineNoConflict,
    InvalidStockAdjustmentLineProduct,
    InvalidStockAdjustmentLineUnit,
    InvalidStockAdjustmentLineBatch,
    StockAdjustmentLineBatchRequired,
    StockAdjustmentLineCostRequired,
    StockAdjustmentNotDraft,
)
WORKFLOW_ERRORS = (
    StockAdjustmentHasNoLines,
    StockAdjustmentNotPostable,
    StockAdjustmentNotCancellable,
    InvalidStockAdjustmentLineProduct,
    InvalidStockAdjustmentLineUnit,
    InvalidStockAdjustmentLineBatch,
    StockAdjustmentLineBatchRequired,
    StockAdjustmentLineCostRequired,
    StockAdjustmentNegativeBalance,
)


def stock_adjustment_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(sort, allowed_fields=ADJUSTMENT_SORT_FIELDS, default=ADJUSTMENT_DEFAULT_SORT)


def stock_adjustment_line_sort(
    sort: Annotated[str | None, Query()] = None,
) -> tuple[SortSpec, ...]:
    return parse_sort(sort, allowed_fields=LINE_SORT_FIELDS, default=LINE_DEFAULT_SORT)


@router.get(
    "",
    response_model=StockAdjustmentListResponse,
    dependencies=[Depends(require_permission("stock_adjustments.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_stock_adjustments(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[StockAdjustmentFilters, Depends(stock_adjustment_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(stock_adjustment_sort)],
):
    return await service.list_stock_adjustments(db, current.tenant_id, pagination, filters, sort)


@router.post(
    "",
    response_model=StockAdjustmentDetailRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("stock_adjustments.create"))],
    responses=error_responses(*AUTH_ERRORS, *CREATE_VALIDATION_ERRORS),
)
async def create_stock_adjustment(
    db: DbSession,
    current: CurrentUser,
    body: StockAdjustmentCreate,
):
    return await service.create_adjustment(
        db,
        current.tenant_id,
        body,
        actor_user_id=current.user_id,
    )


@router.get(
    "/{stock_adjustment_id}",
    response_model=StockAdjustmentDetailRead,
    dependencies=[Depends(require_permission("stock_adjustments.read"))],
    responses=error_responses(*AUTH_ERRORS, StockAdjustmentNotFound),
)
async def get_stock_adjustment(
    db: DbSession,
    current: CurrentUser,
    stock_adjustment_id: uuid.UUID,
):
    adjustment = await service.get_adjustment_detail_by_id(
        db, current.tenant_id, stock_adjustment_id
    )
    if adjustment is None:
        raise StockAdjustmentNotFound()
    return adjustment


@router.patch(
    "/{stock_adjustment_id}",
    response_model=StockAdjustmentDetailRead,
    dependencies=[Depends(require_permission("stock_adjustments.update"))],
    responses=error_responses(
        *AUTH_ERRORS,
        StockAdjustmentNotFound,
        StockAdjustmentNotDraft,
        *CREATE_VALIDATION_ERRORS,
    ),
)
async def update_stock_adjustment(
    db: DbSession,
    current: CurrentUser,
    stock_adjustment_id: uuid.UUID,
    body: StockAdjustmentUpdate,
):
    return await service.update_adjustment(
        db,
        current.tenant_id,
        stock_adjustment_id,
        body,
        actor_user_id=current.user_id,
    )


@router.delete(
    "/{stock_adjustment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("stock_adjustments.delete"))],
    responses=error_responses(
        *AUTH_ERRORS,
        StockAdjustmentNotFound,
        StockAdjustmentNotCancellable,
    ),
)
async def cancel_stock_adjustment(
    db: DbSession,
    current: CurrentUser,
    stock_adjustment_id: uuid.UUID,
) -> None:
    await service.cancel_adjustment(
        db,
        current.tenant_id,
        stock_adjustment_id,
        actor_user_id=current.user_id,
    )


@router.post(
    "/{stock_adjustment_id}/post",
    response_model=StockAdjustmentDetailRead,
    dependencies=[Depends(require_permission("stock_adjustments.update"))],
    responses=error_responses(*AUTH_ERRORS, StockAdjustmentNotFound, *WORKFLOW_ERRORS),
)
async def post_stock_adjustment(
    db: DbSession,
    current: CurrentUser,
    stock_adjustment_id: uuid.UUID,
):
    return await service.post_adjustment(
        db,
        current.tenant_id,
        stock_adjustment_id,
        actor_user_id=current.user_id,
    )


@router.get(
    "/{stock_adjustment_id}/lines",
    response_model=StockAdjustmentLineListResponse,
    dependencies=[Depends(require_permission("stock_adjustments.read"))],
    responses=error_responses(*AUTH_ERRORS, StockAdjustmentNotFound),
)
async def list_stock_adjustment_lines(
    db: DbSession,
    current: CurrentUser,
    stock_adjustment_id: uuid.UUID,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[StockAdjustmentLineFilters, Depends(stock_adjustment_line_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(stock_adjustment_line_sort)],
):
    return await service.list_lines(
        db,
        current.tenant_id,
        stock_adjustment_id,
        pagination,
        filters,
        sort,
    )


@router.post(
    "/{stock_adjustment_id}/lines",
    response_model=StockAdjustmentLineRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("stock_adjustments.create"))],
    responses=error_responses(*AUTH_ERRORS, StockAdjustmentNotFound, *LINE_VALIDATION_ERRORS),
)
async def create_stock_adjustment_line(
    db: DbSession,
    current: CurrentUser,
    stock_adjustment_id: uuid.UUID,
    body: StockAdjustmentLineCreate,
):
    return await service.create_line(
        db,
        current.tenant_id,
        stock_adjustment_id,
        body,
        actor_user_id=current.user_id,
    )


@router.get(
    "/{stock_adjustment_id}/lines/{line_id}",
    response_model=StockAdjustmentLineRead,
    dependencies=[Depends(require_permission("stock_adjustments.read"))],
    responses=error_responses(*AUTH_ERRORS, StockAdjustmentNotFound, StockAdjustmentLineNotFound),
)
async def get_stock_adjustment_line(
    db: DbSession,
    current: CurrentUser,
    stock_adjustment_id: uuid.UUID,
    line_id: uuid.UUID,
):
    adjustment = await service.get_by_id(db, current.tenant_id, stock_adjustment_id)
    if adjustment is None:
        raise StockAdjustmentNotFound()
    line = await service.get_line_by_id(db, current.tenant_id, stock_adjustment_id, line_id)
    if line is None:
        raise StockAdjustmentLineNotFound()
    return line


@router.patch(
    "/{stock_adjustment_id}/lines/{line_id}",
    response_model=StockAdjustmentLineRead,
    dependencies=[Depends(require_permission("stock_adjustments.update"))],
    responses=error_responses(
        *AUTH_ERRORS,
        StockAdjustmentNotFound,
        StockAdjustmentLineNotFound,
        *LINE_VALIDATION_ERRORS,
    ),
)
async def update_stock_adjustment_line(
    db: DbSession,
    current: CurrentUser,
    stock_adjustment_id: uuid.UUID,
    line_id: uuid.UUID,
    body: StockAdjustmentLineUpdate,
):
    return await service.update_line(
        db,
        current.tenant_id,
        stock_adjustment_id,
        line_id,
        body,
        actor_user_id=current.user_id,
    )


@router.delete(
    "/{stock_adjustment_id}/lines/{line_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("stock_adjustments.delete"))],
    responses=error_responses(
        *AUTH_ERRORS,
        StockAdjustmentNotFound,
        StockAdjustmentLineNotFound,
        StockAdjustmentNotDraft,
    ),
)
async def delete_stock_adjustment_line(
    db: DbSession,
    current: CurrentUser,
    stock_adjustment_id: uuid.UUID,
    line_id: uuid.UUID,
) -> None:
    await service.delete_line(
        db,
        current.tenant_id,
        stock_adjustment_id,
        line_id,
        actor_user_id=current.user_id,
    )
