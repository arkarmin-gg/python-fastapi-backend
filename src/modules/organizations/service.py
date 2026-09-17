import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.audit_logs.service import record_audit_log
from src.modules.organizations.exceptions import OrganizationCodeConflict, OrganizationNotFound
from src.modules.organizations.models import Organization
from src.modules.organizations.schemas import (
    OrganizationFilters,
    OrganizationUpdate,
)
from src.pagination import Page, PaginationParams, paginate
from src.query_filters import SortSpec, apply_sort, search_clause

ORG_SORT_COLUMNS = {
    "code": Organization.code,
    "name": Organization.name,
    "created_at": Organization.created_at,
    "id": Organization.id,
}


async def get_by_id(db: AsyncSession, organization_id: uuid.UUID) -> Organization | None:
    return await db.get(Organization, organization_id)


async def get_scoped_by_id(
    db: AsyncSession,
    organization_id: uuid.UUID,
    *,
    scope_organization_id: uuid.UUID,
) -> Organization | None:
    return await db.scalar(
        select(Organization).where(
            Organization.id == organization_id,
            Organization.id == scope_organization_id,
        )
    )


async def get_by_code(db: AsyncSession, code: str) -> Organization | None:
    return await db.scalar(select(Organization).where(Organization.code == code))


async def list_organizations(
    db: AsyncSession,
    organization_id: uuid.UUID,
    pagination: PaginationParams,
    filters: OrganizationFilters,
    sort: tuple[SortSpec, ...],
) -> Page[Organization]:
    stmt = _apply_filters(
        select(Organization).where(Organization.id == organization_id),
        filters,
    )
    stmt = apply_sort(stmt, sort, ORG_SORT_COLUMNS)
    count_stmt = _apply_filters(
        select(func.count(Organization.id)).where(Organization.id == organization_id),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def update(
    db: AsyncSession,
    organization_id: uuid.UUID,
    data: OrganizationUpdate,
    *,
    actor_user_id: uuid.UUID,
    actor_organization_id: uuid.UUID,
    actor_membership_id: uuid.UUID | None = None,
) -> Organization:
    organization = await get_scoped_by_id(
        db,
        organization_id,
        scope_organization_id=actor_organization_id,
    )
    if organization is None:
        raise OrganizationNotFound()
    before = _loggable(organization)
    fields = data.model_dump(exclude_unset=True)
    new_code = fields.get("code")
    if new_code is not None and new_code != organization.code and await get_by_code(db, new_code):
        raise OrganizationCodeConflict()
    for key, value in fields.items():
        setattr(organization, key, value)
    now = datetime.now(UTC)
    if "status" in fields:
        if organization.status.value == "suspended":
            organization.suspended_at = now
        elif organization.status.value == "deleted":
            organization.deleted_at = now
        elif organization.status.value == "active":
            organization.suspended_at = None
            organization.deleted_at = None
    await db.flush()
    await record_audit_log(
        db,
        organization_id=actor_organization_id,
        actor_user_id=actor_user_id,
        actor_membership_id=actor_membership_id,
        action="organizations.update",
        entity_type="organization",
        entity_id=organization.id,
        before_json=before,
        after_json=_loggable(organization),
    )
    await db.commit()
    await db.refresh(organization)
    return organization


def _apply_filters[StmtT: Select[Any]](stmt: StmtT, filters: OrganizationFilters) -> StmtT:
    search = search_clause([Organization.code, Organization.name], filters.search)
    if search is not None:
        stmt = stmt.where(search)
    if filters.status is not None:
        stmt = stmt.where(Organization.status == filters.status)
    return stmt


def _loggable(organization: Organization) -> dict[str, Any]:
    return {
        "code": organization.code,
        "name": organization.name,
        "status": organization.status.value,
    }
