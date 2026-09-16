import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.foundation_enums import ActorType
from src.modules.audit_logs.models import AuditLog


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
