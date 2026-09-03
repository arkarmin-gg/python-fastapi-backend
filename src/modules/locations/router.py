import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from src.dependencies import DbSession
from src.exceptions import InvalidToken
from src.modules.auth.dependencies import CurrentUser
from src.modules.auth.exceptions import InactiveUser
from src.modules.locations import service
from src.modules.locations.exceptions import (
    InvalidParentLocation,
    LocationCodeConflict,
    LocationNotFound,
)
from src.modules.locations.schemas import (
    LocationCreate,
    LocationFilters,
    LocationListResponse,
    LocationRead,
    LocationUpdate,
    location_filters,
)
from src.modules.rbac.dependencies import require_permission
from src.modules.rbac.exceptions import PermissionDenied
from src.pagination import PaginationParams, pagination_params
from src.query_filters import SortSpec, parse_sort
from src.schemas import error_responses

router = APIRouter(prefix="/locations", tags=["Locations"])

SORT_FIELDS = {"code", "name", "location_type", "created_at", "id"}
DEFAULT_SORT = ("code", "id")
AUTH_ERRORS = (InvalidToken, InactiveUser, PermissionDenied)


def location_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(sort, allowed_fields=SORT_FIELDS, default=DEFAULT_SORT)


@router.get(
    "",
    response_model=LocationListResponse,
    dependencies=[Depends(require_permission("locations.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_locations(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[LocationFilters, Depends(location_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(location_sort)],
):
    return await service.list_locations(db, current.tenant_id, pagination, filters, sort)


@router.post(
    "",
    response_model=LocationRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("locations.create"))],
    responses=error_responses(*AUTH_ERRORS, LocationCodeConflict, InvalidParentLocation),
)
async def create_location(
    db: DbSession,
    current: CurrentUser,
    body: LocationCreate,
):
    return await service.create(db, current.tenant_id, body, actor_user_id=current.user_id)


@router.get(
    "/{location_id}",
    response_model=LocationRead,
    dependencies=[Depends(require_permission("locations.read"))],
    responses=error_responses(*AUTH_ERRORS, LocationNotFound),
)
async def get_location(
    db: DbSession,
    current: CurrentUser,
    location_id: uuid.UUID,
):
    location = await service.get_by_id(db, current.tenant_id, location_id)
    if location is None:
        raise LocationNotFound()
    return location


@router.patch(
    "/{location_id}",
    response_model=LocationRead,
    dependencies=[Depends(require_permission("locations.update"))],
    responses=error_responses(
        *AUTH_ERRORS,
        LocationNotFound,
        LocationCodeConflict,
        InvalidParentLocation,
    ),
)
async def update_location(
    db: DbSession,
    current: CurrentUser,
    location_id: uuid.UUID,
    body: LocationUpdate,
):
    return await service.update(
        db,
        current.tenant_id,
        location_id,
        body,
        actor_user_id=current.user_id,
    )


@router.delete(
    "/{location_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("locations.delete"))],
    responses=error_responses(*AUTH_ERRORS, LocationNotFound),
)
async def deactivate_location(
    db: DbSession,
    current: CurrentUser,
    location_id: uuid.UUID,
) -> None:
    await service.deactivate(db, current.tenant_id, location_id, actor_user_id=current.user_id)
