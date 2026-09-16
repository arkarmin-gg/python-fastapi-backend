from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import Query

from src.foundation_enums import ActorType
from src.pagination import Page
from src.schemas import RequestSchema, ResponseSchema


class AuditLogRead(ResponseSchema):
    id: UUID
    organization_id: UUID | None
    actor_type: ActorType
    actor_user_id: UUID | None
    actor_membership_id: UUID | None
    action: str
    entity_type: str
    entity_id: UUID | None
    before_json: dict | None
    after_json: dict | None
    metadata_json: dict | None
    reason: str | None
    request_id: str | None
    trace_id: str | None
    created_at: datetime


class AuditLogFilters(RequestSchema):
    action: str | None = None
    entity_type: str | None = None
    actor_user_id: UUID | None = None


def audit_log_filters(
    action: Annotated[str | None, Query()] = None,
    entity_type: Annotated[str | None, Query()] = None,
    actor_user_id: Annotated[UUID | None, Query()] = None,
) -> AuditLogFilters:
    return AuditLogFilters(action=action, entity_type=entity_type, actor_user_id=actor_user_id)


AuditLogListResponse = Page[AuditLogRead]
