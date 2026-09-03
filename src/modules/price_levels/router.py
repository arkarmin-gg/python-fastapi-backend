import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from src.dependencies import DbSession
from src.exceptions import InvalidToken
from src.modules.auth.dependencies import CurrentUser
from src.modules.auth.exceptions import InactiveUser
from src.modules.price_levels import service
from src.modules.price_levels.exceptions import PriceLevelCodeConflict, PriceLevelNotFound
from src.modules.price_levels.schemas import (
    PriceLevelCreate,
    PriceLevelFilters,
    PriceLevelListResponse,
    PriceLevelRead,
    PriceLevelUpdate,
    price_level_filters,
)
from src.modules.rbac.dependencies import require_permission
from src.modules.rbac.exceptions import PermissionDenied
from src.pagination import PaginationParams, pagination_params
from src.query_filters import SortSpec, parse_sort
from src.schemas import error_responses

router = APIRouter(prefix="/price-levels", tags=["Price Levels"])

SORT_FIELDS = {"code", "name", "id"}
DEFAULT_SORT = ("code", "id")
AUTH_ERRORS = (InvalidToken, InactiveUser, PermissionDenied)


def price_level_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(sort, allowed_fields=SORT_FIELDS, default=DEFAULT_SORT)


@router.get(
    "",
    response_model=PriceLevelListResponse,
    dependencies=[Depends(require_permission("price_levels.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_price_levels(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[PriceLevelFilters, Depends(price_level_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(price_level_sort)],
):
    return await service.list_price_levels(db, current.tenant_id, pagination, filters, sort)


@router.post(
    "",
    response_model=PriceLevelRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("price_levels.create"))],
    responses=error_responses(*AUTH_ERRORS, PriceLevelCodeConflict),
)
async def create_price_level(db: DbSession, current: CurrentUser, body: PriceLevelCreate):
    return await service.create(db, current.tenant_id, body, actor_user_id=current.user_id)


@router.get(
    "/{price_level_id}",
    response_model=PriceLevelRead,
    dependencies=[Depends(require_permission("price_levels.read"))],
    responses=error_responses(*AUTH_ERRORS, PriceLevelNotFound),
)
async def get_price_level(db: DbSession, current: CurrentUser, price_level_id: uuid.UUID):
    price_level = await service.get_by_id(db, current.tenant_id, price_level_id)
    if price_level is None:
        raise PriceLevelNotFound()
    return price_level


@router.patch(
    "/{price_level_id}",
    response_model=PriceLevelRead,
    dependencies=[Depends(require_permission("price_levels.update"))],
    responses=error_responses(*AUTH_ERRORS, PriceLevelNotFound, PriceLevelCodeConflict),
)
async def update_price_level(
    db: DbSession,
    current: CurrentUser,
    price_level_id: uuid.UUID,
    body: PriceLevelUpdate,
):
    return await service.update(
        db,
        current.tenant_id,
        price_level_id,
        body,
        actor_user_id=current.user_id,
    )


@router.delete(
    "/{price_level_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("price_levels.delete"))],
    responses=error_responses(*AUTH_ERRORS, PriceLevelNotFound),
)
async def deactivate_price_level(
    db: DbSession,
    current: CurrentUser,
    price_level_id: uuid.UUID,
) -> None:
    await service.deactivate(db, current.tenant_id, price_level_id, actor_user_id=current.user_id)
