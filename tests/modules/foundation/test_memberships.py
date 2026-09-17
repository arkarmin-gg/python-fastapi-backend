import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.foundation_enums import MembershipStatus, UserStatus
from src.modules.audit_logs.models import AuditLog
from src.modules.memberships.models import OrganizationMembership

from tests.conftest import auth_header_for, make_organization, make_user_with_permissions


@pytest.mark.asyncio
async def test_membership_lifecycle_is_scoped_and_preserves_global_identity(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    organization = await make_organization(db_session)
    other_organization = await make_organization(db_session)
    actor = await make_user_with_permissions(
        db_session,
        organization=organization,
        permissions=[
            "memberships.read",
            "memberships.invite",
            "memberships.update",
            "memberships.remove",
        ],
    )
    target = await make_user_with_permissions(
        db_session,
        organization=other_organization,
        email="member@example.com",
    )
    await db_session.commit()
    headers = await auth_header_for(actor)

    invited = await client.post(
        "/api/v1/memberships",
        headers={**headers, "X-Request-ID": "request-123", "X-Trace-ID": "trace-456"},
        json={"user_id": str(target.id)},
    )
    assert invited.status_code == 201, invited.text
    membership_id = invited.json()["id"]
    assert invited.json()["status"] == MembershipStatus.INVITED
    assert invited.json()["invited_by_membership_id"] == str(
        actor._test_membership_id  # type: ignore[attr-defined]
    )

    listed = await client.get("/api/v1/memberships", headers=headers)
    assert listed.status_code == 200, listed.text
    assert membership_id in {row["id"] for row in listed.json()["items"]}

    other_membership_id = target._test_membership_id  # type: ignore[attr-defined]
    cross_org = await client.get(
        f"/api/v1/memberships/{other_membership_id}",
        headers=headers,
    )
    assert cross_org.status_code == 404

    activated = await client.patch(
        f"/api/v1/memberships/{membership_id}",
        headers=headers,
        json={"status": MembershipStatus.ACTIVE},
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["status"] == MembershipStatus.ACTIVE
    assert activated.json()["activated_at"] is not None

    removed = await client.delete(
        f"/api/v1/memberships/{membership_id}",
        headers=headers,
    )
    assert removed.status_code == 204, removed.text

    membership = await db_session.get(OrganizationMembership, membership_id)
    assert membership is not None
    assert membership.status == MembershipStatus.REMOVED
    assert membership.removed_at is not None
    await db_session.refresh(target)
    assert target.status == UserStatus.ACTIVE
    original_membership = await db_session.get(OrganizationMembership, other_membership_id)
    assert original_membership is not None
    assert original_membership.status == MembershipStatus.ACTIVE

    audit_actions = set(
        (
            await db_session.scalars(
                select(AuditLog.action).where(
                    AuditLog.organization_id == organization.id,
                    AuditLog.entity_id == membership.id,
                )
            )
        ).all()
    )
    assert {"memberships.invite", "memberships.update", "memberships.remove"} <= audit_actions
    invite_log = await db_session.scalar(
        select(AuditLog).where(
            AuditLog.organization_id == organization.id,
            AuditLog.entity_id == membership.id,
            AuditLog.action == "memberships.invite",
        )
    )
    assert invite_log is not None
    assert invite_log.request_id == "request-123"
    assert invite_log.trace_id == "trace-456"
    assert invite_log.ip_address is not None
    assert invite_log.user_agent is not None


@pytest.mark.asyncio
async def test_membership_list_requires_permission(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    organization = await make_organization(db_session)
    actor = await make_user_with_permissions(db_session, organization=organization)
    await db_session.commit()

    response = await client.get(
        "/api/v1/memberships",
        headers=await auth_header_for(actor),
    )

    assert response.status_code == 403
