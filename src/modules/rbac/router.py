import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from src.dependencies import DbSession
from src.exceptions import InvalidToken
from src.modules.auth.dependencies import CurrentUser
from src.modules.auth.exceptions import InactiveUser
from src.modules.rbac import service
from src.modules.rbac.dependencies import require_permission
from src.modules.rbac.exceptions import (
    InvalidPermission,
    InvalidRole,
    InvalidUser,
    PermissionDenied,
    ProtectedRole,
    RoleAssigned,
    RoleCodeConflict,
    RoleNotFound,
    RolePermissionConflict,
    RolePermissionNotFound,
    UserRoleConflict,
    UserRoleNotFound,
)
from src.modules.rbac.schemas import (
    PermissionRead,
    RoleCreate,
    RoleFilters,
    RoleListResponse,
    RolePermissionCreate,
    RolePermissionFilters,
    RolePermissionListResponse,
    RolePermissionRead,
    RoleRead,
    RoleUpdate,
    UserRoleCreate,
    UserRoleFilters,
    UserRoleListResponse,
    UserRoleRead,
    role_filters,
    role_permission_filters,
    user_role_filters,
)
from src.pagination import PaginationParams, pagination_params
from src.query_filters import SortSpec, parse_sort
from src.schemas import error_responses

router = APIRouter(tags=["RBAC"])

SORT_FIELDS = {"code", "name", "created_at", "id"}
DEFAULT_SORT = ("code", "id")
AUTH_ERRORS = (InvalidToken, InactiveUser, PermissionDenied)


def role_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(sort, allowed_fields=SORT_FIELDS, default=DEFAULT_SORT)


def role_permission_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(
        sort,
        allowed_fields={"role_id", "permission_id", "id"},
        default=("role_id", "permission_id", "id"),
    )


def user_role_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(
        sort,
        allowed_fields={"user_id", "role_id", "id"},
        default=("user_id", "role_id", "id"),
    )


@router.get(
    "/roles",
    response_model=RoleListResponse,
    dependencies=[Depends(require_permission("roles.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_roles(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[RoleFilters, Depends(role_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(role_sort)],
):
    return await service.list_roles(db, current.tenant_id, pagination, filters, sort)


@router.post(
    "/roles",
    response_model=RoleRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("roles.create"))],
    responses=error_responses(*AUTH_ERRORS, RoleCodeConflict, InvalidPermission),
)
async def create_role(db: DbSession, current: CurrentUser, body: RoleCreate):
    return await service.create_role(db, current.tenant_id, body, actor_user_id=current.user_id)


@router.get(
    "/roles/{role_id}",
    response_model=RoleRead,
    dependencies=[Depends(require_permission("roles.read"))],
    responses=error_responses(*AUTH_ERRORS, RoleNotFound),
)
async def get_role(db: DbSession, current: CurrentUser, role_id: uuid.UUID):
    role = await service.get_role_by_id(db, current.tenant_id, role_id)
    if role is None:
        raise RoleNotFound()
    return role


@router.patch(
    "/roles/{role_id}",
    response_model=RoleRead,
    dependencies=[Depends(require_permission("roles.update"))],
    responses=error_responses(
        *AUTH_ERRORS, RoleNotFound, ProtectedRole, RoleCodeConflict, InvalidPermission
    ),
)
async def update_role(db: DbSession, current: CurrentUser, role_id: uuid.UUID, body: RoleUpdate):
    return await service.update_role(
        db,
        current.tenant_id,
        role_id,
        body,
        actor_user_id=current.user_id,
    )


@router.delete(
    "/roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("roles.delete"))],
    responses=error_responses(*AUTH_ERRORS, RoleNotFound, ProtectedRole, RoleAssigned),
)
async def deactivate_role(db: DbSession, current: CurrentUser, role_id: uuid.UUID) -> None:
    await service.deactivate_role(db, current.tenant_id, role_id, actor_user_id=current.user_id)


@router.get(
    "/permissions",
    response_model=list[PermissionRead],
    dependencies=[Depends(require_permission("permissions.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_permissions(db: DbSession):
    return await service.list_permissions(db)


@router.get(
    "/role-permissions",
    response_model=RolePermissionListResponse,
    dependencies=[Depends(require_permission("roles.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_role_permissions(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[RolePermissionFilters, Depends(role_permission_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(role_permission_sort)],
):
    return await service.list_role_permissions(db, current.tenant_id, pagination, filters, sort)


@router.post(
    "/role-permissions",
    response_model=RolePermissionRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("roles.update"))],
    responses=error_responses(
        *AUTH_ERRORS,
        InvalidRole,
        InvalidPermission,
        RolePermissionConflict,
    ),
)
async def create_role_permission(
    db: DbSession,
    current: CurrentUser,
    body: RolePermissionCreate,
):
    return await service.create_role_permission(
        db,
        current.tenant_id,
        body,
        actor_user_id=current.user_id,
    )


@router.get(
    "/role-permissions/{role_permission_id}",
    response_model=RolePermissionRead,
    dependencies=[Depends(require_permission("roles.read"))],
    responses=error_responses(*AUTH_ERRORS, RolePermissionNotFound),
)
async def get_role_permission(
    db: DbSession,
    current: CurrentUser,
    role_permission_id: uuid.UUID,
):
    link = await service.get_role_permission_by_id(
        db,
        current.tenant_id,
        role_permission_id,
    )
    if link is None:
        raise RolePermissionNotFound()
    return link


@router.delete(
    "/role-permissions/{role_permission_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("roles.update"))],
    responses=error_responses(*AUTH_ERRORS, RolePermissionNotFound),
)
async def delete_role_permission(
    db: DbSession,
    current: CurrentUser,
    role_permission_id: uuid.UUID,
) -> None:
    await service.delete_role_permission(
        db,
        current.tenant_id,
        role_permission_id,
        actor_user_id=current.user_id,
    )


@router.get(
    "/user-roles",
    response_model=UserRoleListResponse,
    dependencies=[Depends(require_permission("users.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_user_roles(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[UserRoleFilters, Depends(user_role_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(user_role_sort)],
):
    return await service.list_user_roles(db, current.tenant_id, pagination, filters, sort)


@router.post(
    "/user-roles",
    response_model=UserRoleRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("users.update"))],
    responses=error_responses(*AUTH_ERRORS, InvalidUser, InvalidRole, UserRoleConflict),
)
async def create_user_role(
    db: DbSession,
    current: CurrentUser,
    body: UserRoleCreate,
):
    return await service.create_user_role(
        db,
        current.tenant_id,
        body,
        actor_user_id=current.user_id,
    )


@router.get(
    "/user-roles/{user_role_id}",
    response_model=UserRoleRead,
    dependencies=[Depends(require_permission("users.read"))],
    responses=error_responses(*AUTH_ERRORS, UserRoleNotFound),
)
async def get_user_role(
    db: DbSession,
    current: CurrentUser,
    user_role_id: uuid.UUID,
):
    link = await service.get_user_role_by_id(db, current.tenant_id, user_role_id)
    if link is None:
        raise UserRoleNotFound()
    return link


@router.delete(
    "/user-roles/{user_role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("users.update"))],
    responses=error_responses(*AUTH_ERRORS, UserRoleNotFound),
)
async def delete_user_role(
    db: DbSession,
    current: CurrentUser,
    user_role_id: uuid.UUID,
) -> None:
    await service.delete_user_role(
        db,
        current.tenant_id,
        user_role_id,
        actor_user_id=current.user_id,
    )
