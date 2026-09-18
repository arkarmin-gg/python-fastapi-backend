import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.foundation_enums import MembershipStatus
from src.modules.audit_logs.service import record_audit_log
from src.modules.memberships.exceptions import (
    InvalidMembershipTransition,
    MembershipConflict,
    MembershipNotFound,
    MembershipUserNotFound,
)
from src.modules.memberships.models import OrganizationMembership
from src.modules.memberships.schemas import MembershipFilters, MembershipInvite, MembershipUpdate
from src.modules.users.models import User
from src.pagination import Page, PaginationParams, paginate
from src.query_filters import SortSpec, apply_sort

MEMBERSHIP_SORT_COLUMNS = {
    "user_id": OrganizationMembership.user_id,
    "status": OrganizationMembership.status,
    "created_at": OrganizationMembership.created_at,
    "id": OrganizationMembership.id,
}

ALLOWED_TRANSITIONS = {
    MembershipStatus.INVITED: {MembershipStatus.ACTIVE, MembershipStatus.REMOVED},
    MembershipStatus.ACTIVE: {
        MembershipStatus.SUSPENDED,
        MembershipStatus.INACTIVE,
        MembershipStatus.REMOVED,
    },
    MembershipStatus.SUSPENDED: {
        MembershipStatus.ACTIVE,
        MembershipStatus.INACTIVE,
        MembershipStatus.REMOVED,
    },
    MembershipStatus.INACTIVE: {MembershipStatus.ACTIVE, MembershipStatus.REMOVED},
    MembershipStatus.REMOVED: set(),
}


async def get_by_id(
    db: AsyncSession,
    organization_id: uuid.UUID,
    membership_id: uuid.UUID,
) -> OrganizationMembership | None:
    return await db.scalar(
        select(OrganizationMembership)
        .options(*_membership_load_options())
        .where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.id == membership_id,
        )
    )


async def list_memberships(
    db: AsyncSession,
    organization_id: uuid.UUID,
    pagination: PaginationParams,
    filters: MembershipFilters,
    sort: tuple[SortSpec, ...],
) -> Page[OrganizationMembership]:
    stmt = _apply_filters(
        select(OrganizationMembership)
        .options(*_membership_load_options())
        .where(OrganizationMembership.organization_id == organization_id),
        filters,
    )
    stmt = apply_sort(stmt, sort, MEMBERSHIP_SORT_COLUMNS)
    count_stmt = _apply_filters(
        select(func.count(OrganizationMembership.id)).where(
            OrganizationMembership.organization_id == organization_id
        ),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def invite(
    db: AsyncSession,
    organization_id: uuid.UUID,
    data: MembershipInvite,
    *,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
) -> OrganizationMembership:
    if await db.get(User, data.user_id) is None:
        raise MembershipUserNotFound()
    existing = await db.scalar(
        select(OrganizationMembership.id).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == data.user_id,
        )
    )
    if existing is not None:
        raise MembershipConflict()

    now = datetime.now(UTC)
    membership = OrganizationMembership(
        organization_id=organization_id,
        user_id=data.user_id,
        status=MembershipStatus.INVITED,
        invited_by_membership_id=actor_membership_id,
        invited_at=now,
    )
    db.add(membership)
    await db.flush()
    await record_audit_log(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        actor_membership_id=actor_membership_id,
        action="memberships.invite",
        entity_type="organization_membership",
        entity_id=membership.id,
        after_json=_loggable(membership),
    )
    await db.commit()
    loaded = await get_by_id(db, organization_id, membership.id)
    assert loaded is not None
    return loaded


async def update(
    db: AsyncSession,
    organization_id: uuid.UUID,
    membership_id: uuid.UUID,
    data: MembershipUpdate,
    *,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
) -> OrganizationMembership:
    membership = await get_by_id(db, organization_id, membership_id)
    if membership is None:
        raise MembershipNotFound()
    if data.status == membership.status:
        return membership
    if data.status not in ALLOWED_TRANSITIONS[membership.status]:
        raise InvalidMembershipTransition()

    before = _loggable(membership)
    now = datetime.now(UTC)
    membership.status = data.status
    if data.status == MembershipStatus.ACTIVE:
        membership.joined_at = membership.joined_at or now
        membership.activated_at = now
        membership.suspended_at = None
    elif data.status == MembershipStatus.SUSPENDED:
        membership.suspended_at = now
    elif data.status == MembershipStatus.REMOVED:
        membership.removed_at = now

    await db.flush()
    await record_audit_log(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        actor_membership_id=actor_membership_id,
        action=(
            "memberships.remove"
            if data.status == MembershipStatus.REMOVED
            else "memberships.update"
        ),
        entity_type="organization_membership",
        entity_id=membership.id,
        before_json=before,
        after_json=_loggable(membership),
    )
    await db.commit()
    loaded = await get_by_id(db, organization_id, membership.id)
    assert loaded is not None
    return loaded


async def remove(
    db: AsyncSession,
    organization_id: uuid.UUID,
    membership_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
) -> None:
    await update(
        db,
        organization_id,
        membership_id,
        MembershipUpdate(status=MembershipStatus.REMOVED),
        actor_user_id=actor_user_id,
        actor_membership_id=actor_membership_id,
    )


def _apply_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: MembershipFilters,
) -> StmtT:
    if filters.user_id is not None:
        stmt = stmt.where(OrganizationMembership.user_id == filters.user_id)
    if filters.status is not None:
        stmt = stmt.where(OrganizationMembership.status == filters.status)
    return stmt


def _membership_load_options():
    return (
        selectinload(OrganizationMembership.user),
        selectinload(OrganizationMembership.invited_by_membership).selectinload(
            OrganizationMembership.user
        ),
    )


def _loggable(membership: OrganizationMembership) -> dict[str, Any]:
    return {
        "id": str(membership.id),
        "organization_id": str(membership.organization_id),
        "user_id": str(membership.user_id),
        "status": membership.status.value,
    }
