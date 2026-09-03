import uuid
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.audit_logs.models import AuditLog
from src.modules.audit_logs.schemas import AuditLogFilters
from src.pagination import Page, PaginationParams, paginate
from src.query_filters import SortSpec, apply_sort, search_clause

AUDIT_LOG_SORT_COLUMNS = {
    "created_at": AuditLog.created_at,
    "action": AuditLog.action,
    "entity_type": AuditLog.entity_type,
    "id": AuditLog.id,
}


async def record_audit_log(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    before_json: dict[str, Any] | None = None,
    after_json: dict[str, Any] | None = None,
    reason: str | None = None,
) -> AuditLog:
    log = AuditLog(
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before_json=before_json,
        after_json=after_json,
        reason=reason,
    )
    db.add(log)
    await db.flush()
    return log


async def get_by_id(
    db: AsyncSession, tenant_id: uuid.UUID, audit_log_id: uuid.UUID
) -> AuditLog | None:
    return await db.scalar(
        select(AuditLog).where(AuditLog.tenant_id == tenant_id, AuditLog.id == audit_log_id)
    )


async def list_audit_logs(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: AuditLogFilters,
    sort: tuple[SortSpec, ...],
) -> Page[AuditLog]:
    stmt = _apply_filters(select(AuditLog).where(AuditLog.tenant_id == tenant_id), filters)
    stmt = apply_sort(stmt, sort, AUDIT_LOG_SORT_COLUMNS)
    count_stmt = _apply_filters(
        select(func.count(AuditLog.id)).where(AuditLog.tenant_id == tenant_id), filters
    )
    return await paginate(db, stmt, count_stmt, pagination)


def _apply_filters[StmtT: Select[Any]](stmt: StmtT, filters: AuditLogFilters) -> StmtT:
    search = search_clause([AuditLog.action, AuditLog.entity_type, AuditLog.reason], filters.search)
    if search is not None:
        stmt = stmt.where(search)
    if filters.actor_user_id is not None:
        stmt = stmt.where(AuditLog.actor_user_id == filters.actor_user_id)
    if filters.entity_type is not None:
        stmt = stmt.where(AuditLog.entity_type == filters.entity_type)
    if filters.entity_id is not None:
        stmt = stmt.where(AuditLog.entity_id == filters.entity_id)
    if filters.created_from is not None:
        stmt = stmt.where(AuditLog.created_at >= filters.created_from)
    if filters.created_to is not None:
        stmt = stmt.where(AuditLog.created_at <= filters.created_to)
    return stmt
