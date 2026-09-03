import uuid
from datetime import datetime
from typing import Annotated

from fastapi import Query
from pydantic import model_validator

from src.pagination import Page
from src.query_filters import (
    build_query_model,
    normalize_search,
    parse_datetime_range,
    require_timezone_aware,
)
from src.schemas import RequestSchema, ResponseSchema


class AuditLogRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    actor_user_id: uuid.UUID | None
    action: str
    entity_type: str
    entity_id: uuid.UUID
    before_json: dict | None
    after_json: dict | None
    reason: str | None
    created_at: datetime


AuditLogListResponse = Page[AuditLogRead]


class AuditLogFilters(RequestSchema):
    search: str | None = None
    actor_user_id: uuid.UUID | None = None
    entity_type: str | None = None
    entity_id: uuid.UUID | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None

    @model_validator(mode="after")
    def validate(self):
        self.search = normalize_search(self.search)
        require_timezone_aware(self.created_from, "created_from")
        require_timezone_aware(self.created_to, "created_to")
        if self.created_from and self.created_to and self.created_from > self.created_to:
            raise ValueError("created_from must be before or equal to created_to")
        return self


def audit_log_filters(
    search: Annotated[str | None, Query()] = None,
    actor_user_id: Annotated[uuid.UUID | None, Query()] = None,
    entity_type: Annotated[str | None, Query()] = None,
    entity_id: Annotated[uuid.UUID | None, Query()] = None,
    created_from: Annotated[str | None, Query()] = None,
    created_to: Annotated[str | None, Query()] = None,
) -> AuditLogFilters:
    created_from_dt, created_to_dt = parse_datetime_range(
        created_from,
        created_to,
        from_field="created_from",
        to_field="created_to",
    )
    return build_query_model(
        AuditLogFilters,
        search=search,
        actor_user_id=actor_user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        created_from=created_from_dt,
        created_to=created_to_dt,
    )
