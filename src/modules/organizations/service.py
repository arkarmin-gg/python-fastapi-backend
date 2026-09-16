import uuid
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.audit_logs.service import record_audit_log
from src.modules.organizations.exceptions import OrganizationCodeConflict, OrganizationNotFound
from src.modules.organizations.models import Organization
from src.modules.organizations.schemas import (
    OrganizationCreate,
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


async def get_by_code(db: AsyncSession, code: str) -> Organization | None:
    return await db.scalar(select(Organization).where(Organization.code == code))


async def list_organizations(
    db: AsyncSession,
    pagination: PaginationParams,
    filters: OrganizationFilters,
    sort: tuple[SortSpec, ...],
) -> Page[Organization]:
    stmt = _apply_filters(select(Organization), filters)
    stmt = apply_sort(stmt, sort, ORG_SORT_COLUMNS)
    count_stmt = _apply_filters(select(func.count(Organization.id)), filters)
    return await paginate(db, stmt, count_stmt, pagination)


async def create(
    db: AsyncSession,
    data: OrganizationCreate,
    *,
    actor_user_id: uuid.UUID,
    actor_organization_id: uuid.UUID | None,
    actor_membership_id: uuid.UUID | None = None,
) -> Organization:
    if await get_by_code(db, data.code) is not None:
        raise OrganizationCodeConflict()
    organization = Organization(**data.model_dump())
    db.add(organization)
    await db.flush()
    await record_audit_log(
        db,
        organization_id=actor_organization_id,
        actor_user_id=actor_user_id,
        actor_membership_id=actor_membership_id,
        action="organizations.create",
        entity_type="organization",
        entity_id=organization.id,
        after_json=_loggable(organization),
    )
    await db.commit()
    await db.refresh(organization)
    return organization


async def update(
    db: AsyncSession,
    organization_id: uuid.UUID,
    data: OrganizationUpdate,
    *,
    actor_user_id: uuid.UUID,
    actor_organization_id: uuid.UUID | None,
    actor_membership_id: uuid.UUID | None = None,
) -> Organization:
    organization = await get_by_id(db, organization_id)
    if organization is None:
        raise OrganizationNotFound()
    before = _loggable(organization)
    fields = data.model_dump(exclude_unset=True)
    new_code = fields.get("code")
    if new_code is not None and new_code != organization.code and await get_by_code(db, new_code):
        raise OrganizationCodeConflict()
    for key, value in fields.items():
        setattr(organization, key, value)
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
