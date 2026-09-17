import uuid
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.dependencies import current_request_context
from src.foundation_enums import ActorType
from src.modules.audit_logs.models import AuditLog
from src.modules.audit_logs.schemas import AuditLogFilters
from src.pagination import Page, PaginationParams, paginate
from src.query_filters import SortSpec, apply_sort

AUDIT_SORT_COLUMNS = {
    "created_at": AuditLog.created_at,
    "id": AuditLog.id,
    "action": AuditLog.action,
}


async def get_by_id(
    db: AsyncSession,
    organization_id: uuid.UUID,
    audit_log_id: uuid.UUID,
) -> AuditLog | None:
    return await db.scalar(
        select(AuditLog).where(
            AuditLog.organization_id == organization_id,
            AuditLog.id == audit_log_id,
        )
    )


async def list_audit_logs(
    db: AsyncSession,
    organization_id: uuid.UUID,
    pagination: PaginationParams,
    filters: AuditLogFilters,
    sort: tuple[SortSpec, ...],
) -> Page[AuditLog]:
    stmt = _apply_filters(
        select(AuditLog).where(AuditLog.organization_id == organization_id),
        filters,
    )
    stmt = apply_sort(stmt, sort, AUDIT_SORT_COLUMNS)
    count_stmt = _apply_filters(
        select(func.count(AuditLog.id)).where(AuditLog.organization_id == organization_id),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def record_audit_log(
    db: AsyncSession,
    *,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    actor_membership_id: uuid.UUID | None = None,
    actor_type: ActorType = ActorType.USER,
    actor_snapshot: dict[str, Any] | None = None,
    before_json: dict[str, Any] | None = None,
    after_json: dict[str, Any] | None = None,
    metadata_json: dict[str, Any] | None = None,
    reason: str | None = None,
    request_id: str | None = None,
    trace_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AuditLog:
    request_context = current_request_context()
    if request_context is not None:
        request_id = request_id or request_context.request_id
        trace_id = trace_id or request_context.trace_id
        ip_address = ip_address or request_context.ip_address
        user_agent = user_agent or request_context.user_agent
    row = AuditLog(
        organization_id=organization_id,
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        actor_membership_id=actor_membership_id,
        actor_snapshot=actor_snapshot,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before_json=before_json,
        after_json=after_json,
        metadata_json=metadata_json,
        reason=reason,
        request_id=request_id,
        trace_id=trace_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(row)
    await db.flush()
    return row


def _apply_filters[StmtT: Select[Any]](stmt: StmtT, filters: AuditLogFilters) -> StmtT:
    if filters.action is not None:
        stmt = stmt.where(AuditLog.action == filters.action)
    if filters.entity_type is not None:
        stmt = stmt.where(AuditLog.entity_type == filters.entity_type)
    if filters.actor_user_id is not None:
        stmt = stmt.where(AuditLog.actor_user_id == filters.actor_user_id)
    return stmt
