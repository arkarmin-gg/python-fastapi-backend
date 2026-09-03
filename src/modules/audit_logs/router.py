import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from src.dependencies import DbSession
from src.exceptions import InvalidToken
from src.modules.audit_logs import service
from src.modules.audit_logs.exceptions import AuditLogNotFound
from src.modules.audit_logs.schemas import (
    AuditLogFilters,
    AuditLogListResponse,
    AuditLogRead,
    audit_log_filters,
)
from src.modules.auth.dependencies import CurrentUser
from src.modules.auth.exceptions import InactiveUser
from src.modules.rbac.dependencies import require_permission
from src.modules.rbac.exceptions import PermissionDenied
from src.pagination import PaginationParams, pagination_params
from src.query_filters import SortSpec, parse_sort
from src.schemas import error_responses

router = APIRouter(prefix="/audit-logs", tags=["Audit Logs"])

SORT_FIELDS = {"created_at", "action", "entity_type", "id"}
DEFAULT_SORT = ("-created_at", "id")
AUTH_ERRORS = (InvalidToken, InactiveUser, PermissionDenied)


def audit_log_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
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
    sort: Annotated[tuple[SortSpec, ...], Depends(audit_log_sort)],
):
    return await service.list_audit_logs(db, current.tenant_id, pagination, filters, sort)


@router.get(
    "/{audit_log_id}",
    response_model=AuditLogRead,
    dependencies=[Depends(require_permission("audit_logs.read"))],
    responses=error_responses(*AUTH_ERRORS, AuditLogNotFound),
)
async def get_audit_log(db: DbSession, current: CurrentUser, audit_log_id: uuid.UUID):
    log = await service.get_by_id(db, current.tenant_id, audit_log_id)
    if log is None:
        raise AuditLogNotFound()
    return log
