import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from src.dependencies import DbSession
from src.exceptions import InvalidToken
from src.modules.auth.dependencies import CurrentUser
from src.modules.auth.exceptions import InactiveUser
from src.modules.rbac.dependencies import require_permission
from src.modules.rbac.exceptions import PermissionDenied
from src.modules.stock_counts import service
from src.modules.stock_counts.exceptions import (
    InvalidStockCountLineBatch,
    InvalidStockCountLineProduct,
    InvalidStockCountLocation,
    StockCountDocumentNoConflict,
    StockCountHasNoLines,
    StockCountLineNoConflict,
    StockCountLineNotFound,
    StockCountNegativeBalance,
    StockCountNotApproved,
    StockCountNotCancellable,
    StockCountNotDraft,
    StockCountNotFound,
    StockCountNotPendingApproval,
    StockCountNotSubmittable,
)
from src.modules.stock_counts.schemas import (
    StockCountCreate,
    StockCountDetailRead,
    StockCountFilters,
    StockCountLineCreate,
    StockCountLineFilters,
    StockCountLineListResponse,
    StockCountLineRead,
    StockCountLineUpdate,
    StockCountListResponse,
    StockCountRead,
    StockCountUpdate,
    stock_count_filters,
    stock_count_line_filters,
)
from src.pagination import PaginationParams, pagination_params
from src.query_filters import SortSpec, parse_sort
from src.schemas import error_responses

router = APIRouter(prefix="/stock-counts", tags=["Stock Counts"])

COUNT_SORT_FIELDS = {"document_no", "status", "counted_at", "created_at", "id"}
COUNT_DEFAULT_SORT = ("document_no", "id")
LINE_SORT_FIELDS = {"line_no", "product_variant_id", "stock_batch_id", "id"}
LINE_DEFAULT_SORT = ("line_no", "id")
AUTH_ERRORS = (InvalidToken, InactiveUser, PermissionDenied)
COUNT_VALIDATION_ERRORS = (StockCountDocumentNoConflict, InvalidStockCountLocation)
LINE_VALIDATION_ERRORS = (
    StockCountLineNoConflict,
    InvalidStockCountLineProduct,
    InvalidStockCountLineBatch,
    StockCountNotDraft,
)
WORKFLOW_ERRORS = (
    StockCountHasNoLines,
    StockCountNotSubmittable,
    StockCountNotPendingApproval,
    StockCountNotApproved,
    StockCountNotCancellable,
    StockCountNegativeBalance,
)


def stock_count_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(sort, allowed_fields=COUNT_SORT_FIELDS, default=COUNT_DEFAULT_SORT)


def stock_count_line_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(sort, allowed_fields=LINE_SORT_FIELDS, default=LINE_DEFAULT_SORT)


@router.get(
    "",
    response_model=StockCountListResponse,
    dependencies=[Depends(require_permission("stock_counts.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_stock_counts(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[StockCountFilters, Depends(stock_count_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(stock_count_sort)],
):
    return await service.list_stock_counts(db, current.tenant_id, pagination, filters, sort)


@router.post(
    "",
    response_model=StockCountRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("stock_counts.create"))],
    responses=error_responses(*AUTH_ERRORS, *COUNT_VALIDATION_ERRORS),
)
async def create_stock_count(db: DbSession, current: CurrentUser, body: StockCountCreate):
    return await service.create_count(
        db,
        current.tenant_id,
        body,
        actor_user_id=current.user_id,
    )


@router.get(
    "/{stock_count_id}",
    response_model=StockCountDetailRead,
    dependencies=[Depends(require_permission("stock_counts.read"))],
    responses=error_responses(*AUTH_ERRORS, StockCountNotFound),
)
async def get_stock_count(db: DbSession, current: CurrentUser, stock_count_id: uuid.UUID):
    count = await service.get_count_detail_by_id(db, current.tenant_id, stock_count_id)
    if count is None:
        raise StockCountNotFound()
    return count


@router.patch(
    "/{stock_count_id}",
    response_model=StockCountRead,
    dependencies=[Depends(require_permission("stock_counts.update"))],
    responses=error_responses(
        *AUTH_ERRORS,
        StockCountNotFound,
        StockCountNotDraft,
        *COUNT_VALIDATION_ERRORS,
    ),
)
async def update_stock_count(
    db: DbSession,
    current: CurrentUser,
    stock_count_id: uuid.UUID,
    body: StockCountUpdate,
):
    return await service.update_count(
        db,
        current.tenant_id,
        stock_count_id,
        body,
        actor_user_id=current.user_id,
    )


@router.delete(
    "/{stock_count_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("stock_counts.delete"))],
    responses=error_responses(
        *AUTH_ERRORS,
        StockCountNotFound,
        StockCountNotCancellable,
    ),
)
async def cancel_stock_count(
    db: DbSession,
    current: CurrentUser,
    stock_count_id: uuid.UUID,
) -> None:
    await service.cancel_count(
        db,
        current.tenant_id,
        stock_count_id,
        actor_user_id=current.user_id,
    )


@router.post(
    "/{stock_count_id}/submit",
    response_model=StockCountRead,
    dependencies=[Depends(require_permission("stock_counts.update"))],
    responses=error_responses(*AUTH_ERRORS, StockCountNotFound, *WORKFLOW_ERRORS),
)
async def submit_stock_count(db: DbSession, current: CurrentUser, stock_count_id: uuid.UUID):
    return await service.submit_count(
        db,
        current.tenant_id,
        stock_count_id,
        actor_user_id=current.user_id,
    )


@router.post(
    "/{stock_count_id}/approve",
    response_model=StockCountRead,
    dependencies=[Depends(require_permission("stock_counts.update"))],
    responses=error_responses(*AUTH_ERRORS, StockCountNotFound, *WORKFLOW_ERRORS),
)
async def approve_stock_count(db: DbSession, current: CurrentUser, stock_count_id: uuid.UUID):
    return await service.approve_count(
        db,
        current.tenant_id,
        stock_count_id,
        actor_user_id=current.user_id,
    )


@router.post(
    "/{stock_count_id}/reject",
    response_model=StockCountRead,
    dependencies=[Depends(require_permission("stock_counts.update"))],
    responses=error_responses(*AUTH_ERRORS, StockCountNotFound, *WORKFLOW_ERRORS),
)
async def reject_stock_count(db: DbSession, current: CurrentUser, stock_count_id: uuid.UUID):
    return await service.reject_count(
        db,
        current.tenant_id,
        stock_count_id,
        actor_user_id=current.user_id,
    )


@router.post(
    "/{stock_count_id}/post",
    response_model=StockCountRead,
    dependencies=[Depends(require_permission("stock_counts.update"))],
    responses=error_responses(
        *AUTH_ERRORS,
        StockCountNotFound,
        InvalidStockCountLineBatch,
        *WORKFLOW_ERRORS,
    ),
)
async def post_stock_count(db: DbSession, current: CurrentUser, stock_count_id: uuid.UUID):
    return await service.post_count(
        db,
        current.tenant_id,
        stock_count_id,
        actor_user_id=current.user_id,
    )


@router.get(
    "/{stock_count_id}/lines",
    response_model=StockCountLineListResponse,
    dependencies=[Depends(require_permission("stock_counts.read"))],
    responses=error_responses(*AUTH_ERRORS, StockCountNotFound),
)
async def list_stock_count_lines(
    db: DbSession,
    current: CurrentUser,
    stock_count_id: uuid.UUID,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[StockCountLineFilters, Depends(stock_count_line_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(stock_count_line_sort)],
):
    return await service.list_lines(
        db,
        current.tenant_id,
        stock_count_id,
        pagination,
        filters,
        sort,
    )


@router.post(
    "/{stock_count_id}/lines",
    response_model=StockCountLineRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("stock_counts.create"))],
    responses=error_responses(*AUTH_ERRORS, StockCountNotFound, *LINE_VALIDATION_ERRORS),
)
async def create_stock_count_line(
    db: DbSession,
    current: CurrentUser,
    stock_count_id: uuid.UUID,
    body: StockCountLineCreate,
):
    return await service.create_line(
        db,
        current.tenant_id,
        stock_count_id,
        body,
        actor_user_id=current.user_id,
    )


@router.get(
    "/{stock_count_id}/lines/{line_id}",
    response_model=StockCountLineRead,
    dependencies=[Depends(require_permission("stock_counts.read"))],
    responses=error_responses(*AUTH_ERRORS, StockCountNotFound, StockCountLineNotFound),
)
async def get_stock_count_line(
    db: DbSession,
    current: CurrentUser,
    stock_count_id: uuid.UUID,
    line_id: uuid.UUID,
):
    count = await service.get_by_id(db, current.tenant_id, stock_count_id)
    if count is None:
        raise StockCountNotFound()
    line = await service.get_line_by_id(db, current.tenant_id, stock_count_id, line_id)
    if line is None:
        raise StockCountLineNotFound()
    return line


@router.patch(
    "/{stock_count_id}/lines/{line_id}",
    response_model=StockCountLineRead,
    dependencies=[Depends(require_permission("stock_counts.update"))],
    responses=error_responses(
        *AUTH_ERRORS,
        StockCountNotFound,
        StockCountLineNotFound,
        *LINE_VALIDATION_ERRORS,
    ),
)
async def update_stock_count_line(
    db: DbSession,
    current: CurrentUser,
    stock_count_id: uuid.UUID,
    line_id: uuid.UUID,
    body: StockCountLineUpdate,
):
    return await service.update_line(
        db,
        current.tenant_id,
        stock_count_id,
        line_id,
        body,
        actor_user_id=current.user_id,
    )


@router.delete(
    "/{stock_count_id}/lines/{line_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("stock_counts.delete"))],
    responses=error_responses(
        *AUTH_ERRORS,
        StockCountNotFound,
        StockCountLineNotFound,
        StockCountNotDraft,
    ),
)
async def delete_stock_count_line(
    db: DbSession,
    current: CurrentUser,
    stock_count_id: uuid.UUID,
    line_id: uuid.UUID,
) -> None:
    await service.delete_line(
        db,
        current.tenant_id,
        stock_count_id,
        line_id,
        actor_user_id=current.user_id,
    )
