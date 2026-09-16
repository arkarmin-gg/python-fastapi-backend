from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Select, func, select

from src.dependencies import DbSession
from src.exceptions import InvalidToken
from src.modules.audit_logs.models import AuditLog
from src.modules.audit_logs.schemas import (
    AuditLogFilters,
    AuditLogListResponse,
    audit_log_filters,
)
from src.modules.auth.dependencies import CurrentUser
from src.modules.auth.exceptions import InactiveUser
from src.modules.rbac.dependencies import require_permission
from src.modules.rbac.exceptions import PermissionDenied
from src.pagination import PaginationParams, paginate, pagination_params
from src.query_filters import SortSpec, apply_sort, parse_sort
from src.schemas import error_responses

router = APIRouter(prefix="/audit-logs", tags=["Audit Logs"])
AUTH_ERRORS = (InvalidToken, InactiveUser, PermissionDenied)
SORT_FIELDS = {"created_at", "id", "action"}
DEFAULT_SORT = ("-created_at", "id")
SORT_COLUMNS = {
    "created_at": AuditLog.created_at,
    "id": AuditLog.id,
    "action": AuditLog.action,
}


def audit_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(sort, allowed_fields=SORT_FIELDS, default=DEFAULT_SORT)


@router.get(
    "",
    response_model=AuditLogListResponse,
    dependencies=[Depends(require_permission("audit_logs.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_audit_logs(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[AuditLogFilters, Depends(audit_log_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(audit_sort)],
):
    stmt: Select = select(AuditLog).where(AuditLog.organization_id == current.organization_id)
    if filters.action:
        stmt = stmt.where(AuditLog.action == filters.action)
    if filters.entity_type:
        stmt = stmt.where(AuditLog.entity_type == filters.entity_type)
    if filters.actor_user_id:
        stmt = stmt.where(AuditLog.actor_user_id == filters.actor_user_id)
    stmt = apply_sort(stmt, sort, SORT_COLUMNS)
    count_stmt = select(func.count(AuditLog.id)).where(
        AuditLog.organization_id == current.organization_id
    )
    if filters.action:
        count_stmt = count_stmt.where(AuditLog.action == filters.action)
    if filters.entity_type:
        count_stmt = count_stmt.where(AuditLog.entity_type == filters.entity_type)
    if filters.actor_user_id:
        count_stmt = count_stmt.where(AuditLog.actor_user_id == filters.actor_user_id)
    return await paginate(db, stmt, count_stmt, pagination)
