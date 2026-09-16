import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from src.dependencies import DbSession
from src.exceptions import InvalidToken
from src.modules.auth.dependencies import CurrentUser
from src.modules.auth.exceptions import InactiveUser
from src.modules.organizations import service
from src.modules.organizations.exceptions import OrganizationCodeConflict, OrganizationNotFound
from src.modules.organizations.schemas import (
    OrganizationCreate,
    OrganizationFilters,
    OrganizationListResponse,
    OrganizationRead,
    OrganizationUpdate,
    organization_filters,
)
from src.modules.rbac.dependencies import require_permission
from src.modules.rbac.exceptions import PermissionDenied
from src.pagination import PaginationParams, pagination_params
from src.query_filters import SortSpec, parse_sort
from src.schemas import error_responses

router = APIRouter(prefix="/organizations", tags=["Organizations"])

SORT_FIELDS = {"code", "name", "created_at", "id"}
DEFAULT_SORT = ("code", "id")
AUTH_ERRORS = (InvalidToken, InactiveUser, PermissionDenied)


def organization_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(sort, allowed_fields=SORT_FIELDS, default=DEFAULT_SORT)


@router.get(
    "",
    response_model=OrganizationListResponse,
    dependencies=[Depends(require_permission("organizations.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_organizations(
    db: DbSession,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[OrganizationFilters, Depends(organization_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(organization_sort)],
):
    return await service.list_organizations(db, pagination, filters, sort)


@router.post(
    "",
    response_model=OrganizationRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("organizations.create"))],
    responses=error_responses(*AUTH_ERRORS, OrganizationCodeConflict),
)
async def create_organization(db: DbSession, current: CurrentUser, body: OrganizationCreate):
    return await service.create(
        db,
        body,
        actor_user_id=current.user_id,
        actor_organization_id=current.organization_id,
        actor_membership_id=current.membership_id,
    )


@router.get(
    "/{organization_id}",
    response_model=OrganizationRead,
    dependencies=[Depends(require_permission("organizations.read"))],
    responses=error_responses(*AUTH_ERRORS, OrganizationNotFound),
)
async def get_organization(db: DbSession, organization_id: uuid.UUID):
    organization = await service.get_by_id(db, organization_id)
    if organization is None:
        raise OrganizationNotFound()
    return organization


@router.patch(
    "/{organization_id}",
    response_model=OrganizationRead,
    dependencies=[Depends(require_permission("organizations.update"))],
    responses=error_responses(*AUTH_ERRORS, OrganizationNotFound, OrganizationCodeConflict),
)
async def update_organization(
    db: DbSession,
    current: CurrentUser,
    organization_id: uuid.UUID,
    body: OrganizationUpdate,
):
    return await service.update(
        db,
        organization_id,
        body,
        actor_user_id=current.user_id,
        actor_organization_id=current.organization_id,
        actor_membership_id=current.membership_id,
    )
