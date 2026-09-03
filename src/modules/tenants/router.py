import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from src.dependencies import DbSession
from src.exceptions import InvalidToken
from src.modules.auth.dependencies import CurrentUser
from src.modules.auth.exceptions import InactiveUser
from src.modules.rbac.dependencies import require_permission
from src.modules.rbac.exceptions import PermissionDenied
from src.modules.tenants import service
from src.modules.tenants.exceptions import TenantCodeConflict, TenantNotFound
from src.modules.tenants.schemas import (
    TenantCreate,
    TenantFilters,
    TenantListResponse,
    TenantRead,
    TenantUpdate,
    tenant_filters,
)
from src.pagination import PaginationParams, pagination_params
from src.query_filters import SortSpec, parse_sort
from src.schemas import error_responses

router = APIRouter(prefix="/tenants", tags=["Tenants"])

SORT_FIELDS = {"code", "name", "created_at", "id"}
DEFAULT_SORT = ("code", "id")
AUTH_ERRORS = (InvalidToken, InactiveUser, PermissionDenied)


def tenant_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(sort, allowed_fields=SORT_FIELDS, default=DEFAULT_SORT)


@router.get(
    "",
    response_model=TenantListResponse,
    dependencies=[Depends(require_permission("tenants.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_tenants(
    db: DbSession,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[TenantFilters, Depends(tenant_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(tenant_sort)],
):
    return await service.list_tenants(db, pagination, filters, sort)


@router.post(
    "",
    response_model=TenantRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("tenants.create"))],
    responses=error_responses(*AUTH_ERRORS, TenantCodeConflict),
)
async def create_tenant(db: DbSession, current: CurrentUser, body: TenantCreate):
    return await service.create(
        db,
        body,
        actor_user_id=current.user_id,
        actor_tenant_id=current.tenant_id,
    )


@router.get(
    "/{tenant_id}",
    response_model=TenantRead,
    dependencies=[Depends(require_permission("tenants.read"))],
    responses=error_responses(*AUTH_ERRORS, TenantNotFound),
)
async def get_tenant(db: DbSession, tenant_id: uuid.UUID):
    tenant = await service.get_by_id(db, tenant_id)
    if tenant is None:
        raise TenantNotFound()
    return tenant


@router.patch(
    "/{tenant_id}",
    response_model=TenantRead,
    dependencies=[Depends(require_permission("tenants.update"))],
    responses=error_responses(*AUTH_ERRORS, TenantNotFound, TenantCodeConflict),
)
async def update_tenant(
    db: DbSession,
    current: CurrentUser,
    tenant_id: uuid.UUID,
    body: TenantUpdate,
):
    return await service.update(
        db,
        tenant_id,
        body,
        actor_user_id=current.user_id,
        actor_tenant_id=current.tenant_id,
    )
