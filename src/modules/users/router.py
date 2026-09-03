import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from src.dependencies import DbSession
from src.exceptions import InvalidToken
from src.modules.auth.dependencies import CurrentUser
from src.modules.auth.exceptions import InactiveUser
from src.modules.rbac.dependencies import require_permission
from src.modules.rbac.exceptions import PermissionDenied
from src.modules.users import service
from src.modules.users.exceptions import (
    InvalidRole,
    UserIdentifierConflict,
    UserNotFound,
)
from src.modules.users.schemas import (
    UserCreate,
    UserFilters,
    UserListResponse,
    UserRead,
    UserUpdate,
    user_filters,
)
from src.pagination import PaginationParams, pagination_params
from src.query_filters import SortSpec, parse_sort
from src.schemas import error_responses

router = APIRouter(prefix="/users", tags=["Users"])

SORT_FIELDS = {"name", "email", "created_at", "last_login_at", "id"}
DEFAULT_SORT = ("name", "id")
AUTH_ERRORS = (InvalidToken, InactiveUser, PermissionDenied)


def user_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(sort, allowed_fields=SORT_FIELDS, default=DEFAULT_SORT)


@router.get(
    "",
    response_model=UserListResponse,
    dependencies=[Depends(require_permission("users.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_users(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[UserFilters, Depends(user_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(user_sort)],
):
    return await service.list_users(db, current.tenant_id, pagination, filters, sort)


@router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("users.create"))],
    responses=error_responses(*AUTH_ERRORS, UserIdentifierConflict, InvalidRole),
)
async def create_user(db: DbSession, current: CurrentUser, body: UserCreate):
    return await service.create(db, current.tenant_id, body, actor_user_id=current.user_id)


@router.get(
    "/{user_id}",
    response_model=UserRead,
    dependencies=[Depends(require_permission("users.read"))],
    responses=error_responses(*AUTH_ERRORS, UserNotFound),
)
async def get_user(db: DbSession, current: CurrentUser, user_id: uuid.UUID):
    user = await service.get_by_id(db, current.tenant_id, user_id)
    if user is None:
        raise UserNotFound()
    return user


@router.patch(
    "/{user_id}",
    response_model=UserRead,
    dependencies=[Depends(require_permission("users.update"))],
    responses=error_responses(*AUTH_ERRORS, UserNotFound, UserIdentifierConflict, InvalidRole),
)
async def update_user(db: DbSession, current: CurrentUser, user_id: uuid.UUID, body: UserUpdate):
    return await service.update(db, current.tenant_id, user_id, body, actor_user_id=current.user_id)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("users.delete"))],
    responses=error_responses(*AUTH_ERRORS, UserNotFound),
)
async def deactivate_user(db: DbSession, current: CurrentUser, user_id: uuid.UUID):
    await service.deactivate(db, current.tenant_id, user_id, actor_user_id=current.user_id)
