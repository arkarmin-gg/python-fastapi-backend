import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from src.dependencies import DbSession
from src.exceptions import InvalidToken
from src.modules.auth.dependencies import CurrentUser
from src.modules.auth.exceptions import InactiveUser
from src.modules.inventory import service
from src.modules.inventory.exceptions import (
    StockBalanceNotFound,
    StockBatchNotFound,
    StockMovementNotFound,
)
from src.modules.inventory.schemas import (
    StockBalanceFilters,
    StockBalanceGroupBy,
    StockBalanceListResponse,
    StockBalanceRead,
    StockBalanceSummaryListResponse,
    StockBatchFilters,
    StockBatchListResponse,
    StockBatchRead,
    StockMovementFilters,
    StockMovementListResponse,
    StockMovementRead,
    stock_balance_filters,
    stock_batch_filters,
    stock_movement_filters,
)
from src.modules.rbac.dependencies import require_permission
from src.modules.rbac.exceptions import PermissionDenied
from src.pagination import PaginationParams, pagination_params
from src.query_filters import SortSpec, parse_sort
from src.schemas import error_responses

router = APIRouter(tags=["Inventory"])

STOCK_BATCH_SORT_FIELDS = {"received_at", "product_variant_id", "expiry_date", "id"}
STOCK_BATCH_DEFAULT_SORT = ("received_at", "id")
STOCK_MOVEMENT_SORT_FIELDS = {
    "posted_at",
    "product_variant_id",
    "movement_type",
    "id",
}
STOCK_MOVEMENT_DEFAULT_SORT = ("posted_at", "id")
STOCK_BALANCE_SORT_FIELDS = {
    "product_variant_id",
    "location_id",
    "quantity_base",
    "id",
    "product_variant_name",
    "location_name",
    "expiry_date",
    "updated_at",
}
STOCK_BALANCE_DEFAULT_SORT = ("product_variant_id", "location_id", "id")
AUTH_ERRORS = (InvalidToken, InactiveUser, PermissionDenied)


def stock_batch_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(
        sort,
        allowed_fields=STOCK_BATCH_SORT_FIELDS,
        default=STOCK_BATCH_DEFAULT_SORT,
    )


def stock_movement_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(
        sort,
        allowed_fields=STOCK_MOVEMENT_SORT_FIELDS,
        default=STOCK_MOVEMENT_DEFAULT_SORT,
    )


def stock_balance_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(
        sort,
        allowed_fields=STOCK_BALANCE_SORT_FIELDS,
        default=STOCK_BALANCE_DEFAULT_SORT,
    )


@router.get(
    "/stock-batches",
    response_model=StockBatchListResponse,
    dependencies=[Depends(require_permission("inventory.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_stock_batches(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[StockBatchFilters, Depends(stock_batch_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(stock_batch_sort)],
):
    return await service.list_stock_batches(db, current.tenant_id, pagination, filters, sort)


@router.get(
    "/stock-batches/{stock_batch_id}",
    response_model=StockBatchRead,
    dependencies=[Depends(require_permission("inventory.read"))],
    responses=error_responses(*AUTH_ERRORS, StockBatchNotFound),
)
async def get_stock_batch(
    db: DbSession,
    current: CurrentUser,
    stock_batch_id: uuid.UUID,
):
    stock_batch = await service.get_stock_batch_by_id(db, current.tenant_id, stock_batch_id)
    if stock_batch is None:
        raise StockBatchNotFound()
    return stock_batch


@router.get(
    "/stock-movements",
    response_model=StockMovementListResponse,
    dependencies=[Depends(require_permission("inventory.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_stock_movements(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[StockMovementFilters, Depends(stock_movement_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(stock_movement_sort)],
):
    return await service.list_stock_movements(db, current.tenant_id, pagination, filters, sort)


@router.get(
    "/stock-movements/{stock_movement_id}",
    response_model=StockMovementRead,
    dependencies=[Depends(require_permission("inventory.read"))],
    responses=error_responses(*AUTH_ERRORS, StockMovementNotFound),
)
async def get_stock_movement(
    db: DbSession,
    current: CurrentUser,
    stock_movement_id: uuid.UUID,
):
    stock_movement = await service.get_stock_movement_by_id(
        db,
        current.tenant_id,
        stock_movement_id,
    )
    if stock_movement is None:
        raise StockMovementNotFound()
    return stock_movement


@router.get(
    "/stock-balances",
    response_model=StockBalanceListResponse | StockBalanceSummaryListResponse,
    dependencies=[Depends(require_permission("inventory.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_stock_balances(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[StockBalanceFilters, Depends(stock_balance_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(stock_balance_sort)],
    include_zero: Annotated[bool, Query()] = False,
    group_by: Annotated[StockBalanceGroupBy | None, Query()] = None,
    display_unit_id: Annotated[uuid.UUID | None, Query()] = None,
):
    return await service.list_stock_balances(
        db,
        current.tenant_id,
        pagination,
        filters,
        sort,
        include_zero=include_zero,
        group_by=group_by,
        display_unit_id=display_unit_id,
    )


@router.get(
    "/stock-balances/{stock_balance_id}",
    response_model=StockBalanceRead,
    dependencies=[Depends(require_permission("inventory.read"))],
    responses=error_responses(*AUTH_ERRORS, StockBalanceNotFound),
)
async def get_stock_balance(
    db: DbSession,
    current: CurrentUser,
    stock_balance_id: uuid.UUID,
    display_unit_id: Annotated[uuid.UUID | None, Query()] = None,
):
    stock_balance = await service.get_stock_balance_by_id(
        db,
        current.tenant_id,
        stock_balance_id,
        display_unit_id=display_unit_id,
    )
    if stock_balance is None:
        raise StockBalanceNotFound()
    return stock_balance
