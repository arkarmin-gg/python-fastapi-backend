import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from src.dependencies import DbSession
from src.exceptions import InvalidToken
from src.modules.auth.dependencies import CurrentUser
from src.modules.auth.exceptions import InactiveUser
from src.modules.rbac.dependencies import require_permission
from src.modules.rbac.exceptions import PermissionDenied
from src.modules.stock_transfers import service
from src.modules.stock_transfers.exceptions import (
    InvalidStockTransferLineBatch,
    InvalidStockTransferLineLocation,
    InvalidStockTransferLineProduct,
    InvalidStockTransferLineUnit,
    StockTransferDocumentNoConflict,
    StockTransferHasNoLines,
    StockTransferInsufficientBalance,
    StockTransferLineNoConflict,
    StockTransferLineNotFound,
    StockTransferNotCancellable,
    StockTransferNotDraft,
    StockTransferNotFound,
    StockTransferNotPostable,
)
from src.modules.stock_transfers.schemas import (
    StockTransferCreate,
    StockTransferDetailRead,
    StockTransferFilters,
    StockTransferLineCreate,
    StockTransferLineFilters,
    StockTransferLineListResponse,
    StockTransferLineRead,
    StockTransferLineUpdate,
    StockTransferListResponse,
    StockTransferUpdate,
    stock_transfer_filters,
    stock_transfer_line_filters,
)
from src.pagination import PaginationParams, pagination_params
from src.query_filters import SortSpec, parse_sort
from src.schemas import error_responses

router = APIRouter(prefix="/stock-transfers", tags=["Stock Transfers"])

TRANSFER_SORT_FIELDS = {"document_no", "status", "created_at", "id"}
TRANSFER_DEFAULT_SORT = ("document_no", "id")
LINE_SORT_FIELDS = {"line_no", "product_variant_id", "from_location_id", "to_location_id", "id"}
LINE_DEFAULT_SORT = ("line_no", "id")
AUTH_ERRORS = (InvalidToken, InactiveUser, PermissionDenied)
CREATE_VALIDATION_ERRORS = (
    StockTransferDocumentNoConflict,
    InvalidStockTransferLineProduct,
    InvalidStockTransferLineUnit,
    InvalidStockTransferLineBatch,
    InvalidStockTransferLineLocation,
)
LINE_VALIDATION_ERRORS = (
    StockTransferLineNoConflict,
    InvalidStockTransferLineProduct,
    InvalidStockTransferLineUnit,
    InvalidStockTransferLineBatch,
    InvalidStockTransferLineLocation,
    StockTransferNotDraft,
)
WORKFLOW_ERRORS = (
    StockTransferHasNoLines,
    StockTransferNotPostable,
    StockTransferNotCancellable,
    InvalidStockTransferLineProduct,
    InvalidStockTransferLineUnit,
    InvalidStockTransferLineBatch,
    InvalidStockTransferLineLocation,
    StockTransferInsufficientBalance,
)


def stock_transfer_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(sort, allowed_fields=TRANSFER_SORT_FIELDS, default=TRANSFER_DEFAULT_SORT)


def stock_transfer_line_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(sort, allowed_fields=LINE_SORT_FIELDS, default=LINE_DEFAULT_SORT)


@router.get(
    "",
    response_model=StockTransferListResponse,
    dependencies=[Depends(require_permission("stock_transfers.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_stock_transfers(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[StockTransferFilters, Depends(stock_transfer_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(stock_transfer_sort)],
):
    return await service.list_stock_transfers(db, current.tenant_id, pagination, filters, sort)


@router.post(
    "",
    response_model=StockTransferDetailRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("stock_transfers.create"))],
    responses=error_responses(*AUTH_ERRORS, *CREATE_VALIDATION_ERRORS),
)
async def create_stock_transfer(
    db: DbSession,
    current: CurrentUser,
    body: StockTransferCreate,
):
    return await service.create_transfer(
        db,
        current.tenant_id,
        body,
        actor_user_id=current.user_id,
    )


@router.get(
    "/{stock_transfer_id}",
    response_model=StockTransferDetailRead,
    dependencies=[Depends(require_permission("stock_transfers.read"))],
    responses=error_responses(*AUTH_ERRORS, StockTransferNotFound),
)
async def get_stock_transfer(
    db: DbSession,
    current: CurrentUser,
    stock_transfer_id: uuid.UUID,
):
    transfer = await service.get_transfer_detail_by_id(db, current.tenant_id, stock_transfer_id)
    if transfer is None:
        raise StockTransferNotFound()
    return transfer


@router.patch(
    "/{stock_transfer_id}",
    response_model=StockTransferDetailRead,
    dependencies=[Depends(require_permission("stock_transfers.update"))],
    responses=error_responses(
        *AUTH_ERRORS,
        StockTransferNotFound,
        StockTransferNotDraft,
        *CREATE_VALIDATION_ERRORS,
    ),
)
async def update_stock_transfer(
    db: DbSession,
    current: CurrentUser,
    stock_transfer_id: uuid.UUID,
    body: StockTransferUpdate,
):
    return await service.update_transfer(
        db,
        current.tenant_id,
        stock_transfer_id,
        body,
        actor_user_id=current.user_id,
    )


@router.delete(
    "/{stock_transfer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("stock_transfers.delete"))],
    responses=error_responses(
        *AUTH_ERRORS,
        StockTransferNotFound,
        StockTransferNotCancellable,
    ),
)
async def cancel_stock_transfer(
    db: DbSession,
    current: CurrentUser,
    stock_transfer_id: uuid.UUID,
) -> None:
    await service.cancel_transfer(
        db,
        current.tenant_id,
        stock_transfer_id,
        actor_user_id=current.user_id,
    )


@router.post(
    "/{stock_transfer_id}/post",
    response_model=StockTransferDetailRead,
    dependencies=[Depends(require_permission("stock_transfers.update"))],
    responses=error_responses(*AUTH_ERRORS, StockTransferNotFound, *WORKFLOW_ERRORS),
)
async def post_stock_transfer(
    db: DbSession,
    current: CurrentUser,
    stock_transfer_id: uuid.UUID,
):
    return await service.post_transfer(
        db,
        current.tenant_id,
        stock_transfer_id,
        actor_user_id=current.user_id,
    )


@router.get(
    "/{stock_transfer_id}/lines",
    response_model=StockTransferLineListResponse,
    dependencies=[Depends(require_permission("stock_transfers.read"))],
    responses=error_responses(*AUTH_ERRORS, StockTransferNotFound),
)
async def list_stock_transfer_lines(
    db: DbSession,
    current: CurrentUser,
    stock_transfer_id: uuid.UUID,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[StockTransferLineFilters, Depends(stock_transfer_line_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(stock_transfer_line_sort)],
):
    return await service.list_lines(
        db,
        current.tenant_id,
        stock_transfer_id,
        pagination,
        filters,
        sort,
    )


@router.post(
    "/{stock_transfer_id}/lines",
    response_model=StockTransferLineRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("stock_transfers.create"))],
    responses=error_responses(*AUTH_ERRORS, StockTransferNotFound, *LINE_VALIDATION_ERRORS),
)
async def create_stock_transfer_line(
    db: DbSession,
    current: CurrentUser,
    stock_transfer_id: uuid.UUID,
    body: StockTransferLineCreate,
):
    return await service.create_line(
        db,
        current.tenant_id,
        stock_transfer_id,
        body,
        actor_user_id=current.user_id,
    )


@router.get(
    "/{stock_transfer_id}/lines/{line_id}",
    response_model=StockTransferLineRead,
    dependencies=[Depends(require_permission("stock_transfers.read"))],
    responses=error_responses(*AUTH_ERRORS, StockTransferNotFound, StockTransferLineNotFound),
)
async def get_stock_transfer_line(
    db: DbSession,
    current: CurrentUser,
    stock_transfer_id: uuid.UUID,
    line_id: uuid.UUID,
):
    transfer = await service.get_by_id(db, current.tenant_id, stock_transfer_id)
    if transfer is None:
        raise StockTransferNotFound()
    line = await service.get_line_by_id(db, current.tenant_id, stock_transfer_id, line_id)
    if line is None:
        raise StockTransferLineNotFound()
    return line


@router.patch(
    "/{stock_transfer_id}/lines/{line_id}",
    response_model=StockTransferLineRead,
    dependencies=[Depends(require_permission("stock_transfers.update"))],
    responses=error_responses(
        *AUTH_ERRORS,
        StockTransferNotFound,
        StockTransferLineNotFound,
        *LINE_VALIDATION_ERRORS,
    ),
)
async def update_stock_transfer_line(
    db: DbSession,
    current: CurrentUser,
    stock_transfer_id: uuid.UUID,
    line_id: uuid.UUID,
    body: StockTransferLineUpdate,
):
    return await service.update_line(
        db,
        current.tenant_id,
        stock_transfer_id,
        line_id,
        body,
        actor_user_id=current.user_id,
    )


@router.delete(
    "/{stock_transfer_id}/lines/{line_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("stock_transfers.delete"))],
    responses=error_responses(
        *AUTH_ERRORS,
        StockTransferNotFound,
        StockTransferLineNotFound,
        StockTransferNotDraft,
    ),
)
async def delete_stock_transfer_line(
    db: DbSession,
    current: CurrentUser,
    stock_transfer_id: uuid.UUID,
    line_id: uuid.UUID,
) -> None:
    await service.delete_line(
        db,
        current.tenant_id,
        stock_transfer_id,
        line_id,
        actor_user_id=current.user_id,
    )
