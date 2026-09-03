import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from src.dependencies import DbSession
from src.exceptions import InvalidToken
from src.modules.auth.dependencies import CurrentUser
from src.modules.auth.exceptions import InactiveUser
from src.modules.rbac.dependencies import require_permission
from src.modules.rbac.exceptions import PermissionDenied
from src.modules.units import service
from src.modules.units.exceptions import UnitCodeConflict, UnitNotFound
from src.modules.units.schemas import (
    UnitCreate,
    UnitFilters,
    UnitListResponse,
    UnitRead,
    UnitUpdate,
    unit_filters,
)
from src.pagination import PaginationParams, pagination_params
from src.query_filters import SortSpec, parse_sort
from src.schemas import error_responses

router = APIRouter(prefix="/units", tags=["Units"])

SORT_FIELDS = {"code", "name_en", "unit_kind", "id"}
DEFAULT_SORT = ("code", "id")
AUTH_ERRORS = (InvalidToken, InactiveUser, PermissionDenied)


def unit_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(sort, allowed_fields=SORT_FIELDS, default=DEFAULT_SORT)


@router.get(
    "",
    response_model=UnitListResponse,
    dependencies=[Depends(require_permission("units.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_units(
    db: DbSession,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[UnitFilters, Depends(unit_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(unit_sort)],
):
    return await service.list_units(db, pagination, filters, sort)


@router.post(
    "",
    response_model=UnitRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("units.create"))],
    responses=error_responses(*AUTH_ERRORS, UnitCodeConflict),
)
async def create_unit(db: DbSession, current: CurrentUser, body: UnitCreate):
    return await service.create(db, current.tenant_id, body, actor_user_id=current.user_id)


@router.get(
    "/{unit_id}",
    response_model=UnitRead,
    dependencies=[Depends(require_permission("units.read"))],
    responses=error_responses(*AUTH_ERRORS, UnitNotFound),
)
async def get_unit(db: DbSession, unit_id: uuid.UUID):
    unit = await service.get_by_id(db, unit_id)
    if unit is None:
        raise UnitNotFound()
    return unit


@router.patch(
    "/{unit_id}",
    response_model=UnitRead,
    dependencies=[Depends(require_permission("units.update"))],
    responses=error_responses(*AUTH_ERRORS, UnitNotFound, UnitCodeConflict),
)
async def update_unit(db: DbSession, current: CurrentUser, unit_id: uuid.UUID, body: UnitUpdate):
    return await service.update(db, current.tenant_id, unit_id, body, actor_user_id=current.user_id)


@router.delete(
    "/{unit_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("units.delete"))],
    responses=error_responses(*AUTH_ERRORS, UnitNotFound),
)
async def deactivate_unit(db: DbSession, current: CurrentUser, unit_id: uuid.UUID) -> None:
    await service.deactivate(db, current.tenant_id, unit_id, actor_user_id=current.user_id)
