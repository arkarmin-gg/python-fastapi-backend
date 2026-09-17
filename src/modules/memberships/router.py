import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from src.dependencies import DbSession
from src.exceptions import InvalidToken
from src.modules.auth.dependencies import CurrentUser
from src.modules.auth.exceptions import InactiveUser
from src.modules.memberships import service
from src.modules.memberships.exceptions import (
    InvalidMembershipTransition,
    MembershipConflict,
    MembershipNotFound,
    MembershipUserNotFound,
)
from src.modules.memberships.schemas import (
    MembershipFilters,
    MembershipInvite,
    MembershipListResponse,
    MembershipRead,
    MembershipUpdate,
    membership_filters,
)
from src.modules.rbac.dependencies import require_permission
from src.modules.rbac.exceptions import PermissionDenied
from src.pagination import PaginationParams, pagination_params
from src.query_filters import SortSpec, parse_sort
from src.schemas import error_responses

router = APIRouter(prefix="/memberships", tags=["Memberships"])
AUTH_ERRORS = (InvalidToken, InactiveUser, PermissionDenied)


def membership_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(
        sort,
        allowed_fields={"user_id", "status", "created_at", "id"},
        default=("created_at", "id"),
    )


@router.get(
    "",
    response_model=MembershipListResponse,
    dependencies=[Depends(require_permission("memberships.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_memberships(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[MembershipFilters, Depends(membership_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(membership_sort)],
):
    return await service.list_memberships(
        db,
        current.organization_id,
        pagination,
        filters,
        sort,
    )


@router.post(
    "",
    response_model=MembershipRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("memberships.invite"))],
    responses=error_responses(
        *AUTH_ERRORS,
        MembershipConflict,
        MembershipUserNotFound,
    ),
)
async def invite_membership(db: DbSession, current: CurrentUser, body: MembershipInvite):
    return await service.invite(
        db,
        current.organization_id,
        body,
        actor_user_id=current.user_id,
        actor_membership_id=current.membership_id,
    )


@router.get(
    "/{membership_id}",
    response_model=MembershipRead,
    dependencies=[Depends(require_permission("memberships.read"))],
    responses=error_responses(*AUTH_ERRORS, MembershipNotFound),
)
async def get_membership(db: DbSession, current: CurrentUser, membership_id: uuid.UUID):
    membership = await service.get_by_id(db, current.organization_id, membership_id)
    if membership is None:
        raise MembershipNotFound()
    return membership


@router.patch(
    "/{membership_id}",
    response_model=MembershipRead,
    dependencies=[Depends(require_permission("memberships.update"))],
    responses=error_responses(*AUTH_ERRORS, MembershipNotFound, InvalidMembershipTransition),
)
async def update_membership(
    db: DbSession,
    current: CurrentUser,
    membership_id: uuid.UUID,
    body: MembershipUpdate,
):
    return await service.update(
        db,
        current.organization_id,
        membership_id,
        body,
        actor_user_id=current.user_id,
        actor_membership_id=current.membership_id,
    )


@router.delete(
    "/{membership_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("memberships.remove"))],
    responses=error_responses(*AUTH_ERRORS, MembershipNotFound, InvalidMembershipTransition),
)
async def remove_membership(
    db: DbSession,
    current: CurrentUser,
    membership_id: uuid.UUID,
) -> None:
    await service.remove(
        db,
        current.organization_id,
        membership_id,
        actor_user_id=current.user_id,
        actor_membership_id=current.membership_id,
    )
