import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from src.modules.audit_logs.models import AuditLog

from tests.conftest import auth_header_for, make_organization, make_user_with_permissions


@pytest.mark.asyncio
async def test_audit_log_list_and_get_are_organization_scoped(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    organization = await make_organization(db_session)
    other_organization = await make_organization(db_session)
    actor = await make_user_with_permissions(
        db_session,
        organization=organization,
        permissions=["audit_logs.read"],
    )
    own_log = AuditLog(
        organization_id=organization.id,
        actor_user_id=actor.id,
        actor_membership_id=actor._test_membership_id,  # type: ignore[attr-defined]
        action="test.action",
        entity_type="test",
    )
    other_log = AuditLog(
        organization_id=other_organization.id,
        action="test.action",
        entity_type="test",
    )
    db_session.add_all([own_log, other_log])
    await db_session.commit()
    headers = await auth_header_for(actor)

    listed = await client.get(
        "/api/v1/audit-logs?action=%20%20&entity_type=%20%20",
        headers=headers,
    )
    assert listed.status_code == 200, listed.text
    assert [str(own_log.id)] == [row["id"] for row in listed.json()["items"]]

    fetched = await client.get(f"/api/v1/audit-logs/{own_log.id}", headers=headers)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["id"] == str(own_log.id)

    cross_org = await client.get(f"/api/v1/audit-logs/{other_log.id}", headers=headers)
    assert cross_org.status_code == 404
