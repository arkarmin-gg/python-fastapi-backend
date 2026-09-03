import uuid
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.audit_logs.service import record_audit_log
from src.modules.tenants.exceptions import TenantCodeConflict, TenantNotFound
from src.modules.tenants.models import Tenant
from src.modules.tenants.schemas import TenantCreate, TenantFilters, TenantUpdate
from src.pagination import Page, PaginationParams, paginate
from src.query_filters import SortSpec, apply_sort, search_clause

TENANT_SORT_COLUMNS = {
    "code": Tenant.code,
    "name": Tenant.name,
    "created_at": Tenant.created_at,
    "id": Tenant.id,
}


async def get_by_id(db: AsyncSession, tenant_id: uuid.UUID) -> Tenant | None:
    return await db.get(Tenant, tenant_id)


async def get_by_code(db: AsyncSession, code: str) -> Tenant | None:
    return await db.scalar(select(Tenant).where(Tenant.code == code))


async def list_tenants(
    db: AsyncSession,
    pagination: PaginationParams,
    filters: TenantFilters,
    sort: tuple[SortSpec, ...],
) -> Page[Tenant]:
    stmt = _apply_filters(select(Tenant), filters)
    stmt = apply_sort(stmt, sort, TENANT_SORT_COLUMNS)
    count_stmt = _apply_filters(select(func.count(Tenant.id)), filters)
    return await paginate(db, stmt, count_stmt, pagination)


async def create(
    db: AsyncSession,
    data: TenantCreate,
    *,
    actor_user_id: uuid.UUID,
    actor_tenant_id: uuid.UUID,
) -> Tenant:
    if await get_by_code(db, data.code) is not None:
        raise TenantCodeConflict()
    tenant = Tenant(**data.model_dump())
    db.add(tenant)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=actor_tenant_id,
        actor_user_id=actor_user_id,
        action="tenants.create",
        entity_type="tenant",
        entity_id=tenant.id,
        after_json=_loggable(tenant),
    )
    await db.commit()
    await db.refresh(tenant)
    return tenant


async def update(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: TenantUpdate,
    *,
    actor_user_id: uuid.UUID,
    actor_tenant_id: uuid.UUID,
) -> Tenant:
    tenant = await get_by_id(db, tenant_id)
    if tenant is None:
        raise TenantNotFound()
    before = _loggable(tenant)
    fields = data.model_dump(exclude_unset=True)
    new_code = fields.get("code")
    if new_code is not None and new_code != tenant.code and await get_by_code(db, new_code):
        raise TenantCodeConflict()
    for key, value in fields.items():
        setattr(tenant, key, value)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=actor_tenant_id,
        actor_user_id=actor_user_id,
        action="tenants.update",
        entity_type="tenant",
        entity_id=tenant.id,
        before_json=before,
        after_json=_loggable(tenant),
    )
    await db.commit()
    await db.refresh(tenant)
    return tenant


def _apply_filters[StmtT: Select[Any]](stmt: StmtT, filters: TenantFilters) -> StmtT:
    search = search_clause([Tenant.code, Tenant.name, Tenant.legal_name], filters.search)
    if search is not None:
        stmt = stmt.where(search)
    if filters.status is not None:
        stmt = stmt.where(Tenant.status == filters.status)
    return stmt


def _loggable(tenant: Tenant) -> dict[str, Any]:
    return {
        "code": tenant.code,
        "name": tenant.name,
        "status": tenant.status.value,
        "currency_code": tenant.currency_code,
    }
