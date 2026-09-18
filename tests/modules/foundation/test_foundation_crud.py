from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.foundation_enums import OrganizationStatus
from src.modules.rbac.models import MembershipRole, Permission, RolePermission

from tests.conftest import auth_header_for, make_organization, make_user_with_permissions


@pytest.mark.asyncio
async def test_list_organizations_requires_permission(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org = await make_organization(db_session)
    user = await make_user_with_permissions(db_session, organization=org, permissions=[])
    await db_session.commit()
    headers = await auth_header_for(user)
    response = await client.get("/api/v1/organizations", headers=headers)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_list_organizations_ok(client: AsyncClient, db_session: AsyncSession) -> None:
    org = await make_organization(db_session, code="acme")
    await make_organization(db_session, code="other")
    user = await make_user_with_permissions(
        db_session,
        organization=org,
        permissions=["organizations.read"],
    )
    await db_session.commit()
    headers = await auth_header_for(user)
    response = await client.get("/api/v1/organizations", headers=headers)
    assert response.status_code == 200, response.text
    codes = [row["code"] for row in response.json()["items"]]
    assert codes == ["acme"]


@pytest.mark.asyncio
async def test_get_organization_hides_other_organization(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org = await make_organization(db_session)
    other = await make_organization(db_session)
    user = await make_user_with_permissions(
        db_session,
        organization=org,
        permissions=["organizations.read"],
    )
    await db_session.commit()

    response = await client.get(
        f"/api/v1/organizations/{other.id}",
        headers=await auth_header_for(user),
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_organization_hides_other_organization(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org = await make_organization(db_session)
    other = await make_organization(db_session)
    user = await make_user_with_permissions(
        db_session,
        organization=org,
        permissions=["organizations.update"],
    )
    await db_session.commit()

    response = await client.patch(
        f"/api/v1/organizations/{other.id}",
        headers=await auth_header_for(user),
        json={"name": "Compromised"},
    )

    assert response.status_code == 404
    await db_session.refresh(other)
    assert other.name != "Compromised"


@pytest.mark.asyncio
async def test_suspending_organization_sets_lifecycle_timestamp(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org = await make_organization(db_session)
    user = await make_user_with_permissions(
        db_session,
        organization=org,
        permissions=["organizations.update"],
    )
    await db_session.commit()

    response = await client.patch(
        f"/api/v1/organizations/{org.id}",
        headers=await auth_header_for(user),
        json={"status": "suspended"},
    )

    assert response.status_code == 200, response.text
    await db_session.refresh(org)
    assert org.status == OrganizationStatus.SUSPENDED
    assert org.suspended_at is not None


@pytest.mark.asyncio
async def test_suspended_organization_rejects_existing_access_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org = await make_organization(db_session)
    user = await make_user_with_permissions(
        db_session,
        organization=org,
        permissions=["organizations.read"],
    )
    headers = await auth_header_for(user)
    org.status = OrganizationStatus.SUSPENDED
    org.suspended_at = datetime.now(UTC)
    await db_session.commit()

    response = await client.get("/api/v1/organizations", headers=headers)

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_expired_membership_role_does_not_authorize(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org = await make_organization(db_session)
    user = await make_user_with_permissions(
        db_session,
        organization=org,
        permissions=["organizations.read"],
    )
    role_link = await db_session.scalar(
        select(MembershipRole).where(
            MembershipRole.membership_id == user._test_membership_id,  # type: ignore[attr-defined]
        )
    )
    assert role_link is not None
    now = datetime.now(UTC)
    role_link.assigned_at = now - timedelta(seconds=2)
    role_link.expires_at = now - timedelta(seconds=1)
    await db_session.commit()

    response = await client.get(
        "/api/v1/organizations",
        headers=await auth_header_for(user),
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_role_and_list(client: AsyncClient, db_session: AsyncSession) -> None:
    org = await make_organization(db_session)
    user = await make_user_with_permissions(
        db_session,
        organization=org,
        permissions=["roles.create", "roles.read", "permissions.read"],
    )
    await db_session.commit()
    headers = await auth_header_for(user)

    created = await client.post(
        "/api/v1/roles",
        headers=headers,
        json={"code": "manager", "name": "Manager", "permission_ids": []},
    )
    assert created.status_code == 201, created.text
    assert created.json()["code"] == "manager"

    listed = await client.get("/api/v1/roles", headers=headers)
    assert listed.status_code == 200, listed.text
    codes = [row["code"] for row in listed.json()["items"]]
    assert "manager" in codes


@pytest.mark.asyncio
async def test_update_role_replaces_permissions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org = await make_organization(db_session)
    actor = await make_user_with_permissions(
        db_session,
        organization=org,
        permissions=["roles.create", "roles.read", "roles.update"],
    )
    permissions = [
        Permission(code=f"test.role-update-{index}", name=f"Permission {index}", module="test")
        for index in range(6)
    ]
    db_session.add_all(permissions)
    await db_session.commit()

    created = await client.post(
        "/api/v1/roles",
        headers=await auth_header_for(actor),
        json={
            "code": "viewer",
            "name": "Viewer",
            "permission_ids": [str(permission.id) for permission in permissions[:3]],
        },
    )
    assert created.status_code == 201, created.text

    updated = await client.patch(
        f"/api/v1/roles/{created.json()['id']}",
        headers=await auth_header_for(actor),
        json={
            "code": "viewer",
            "name": "Viewer",
            "description": "This is viewer role",
            "is_active": True,
            "permission_ids": [str(permission.id) for permission in permissions],
        },
    )

    assert updated.status_code == 200, updated.text
    assert {permission["id"] for permission in updated.json()["permissions"]} == {
        str(permission.id) for permission in permissions
    }


@pytest.mark.asyncio
async def test_create_and_get_user_are_organization_scoped(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    organization = await make_organization(db_session)
    other_organization = await make_organization(db_session)
    actor = await make_user_with_permissions(
        db_session,
        organization=organization,
        permissions=["users.create", "users.read"],
    )
    other_user = await make_user_with_permissions(
        db_session,
        organization=other_organization,
    )
    await db_session.commit()
    headers = await auth_header_for(actor)

    created = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "name": "New Member",
            "email": "new-member@example.com",
            "password": "Password123!",
            "role_ids": [],
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["email"] == "new-member@example.com"

    duplicate = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "name": "Duplicate Member",
            "email": "NEW-MEMBER@example.com",
            "password": "Password123!",
            "role_ids": [],
        },
    )
    assert duplicate.status_code == 409

    fetched = await client.get(f"/api/v1/users/{created.json()['id']}", headers=headers)
    assert fetched.status_code == 200, fetched.text

    cross_org = await client.get(f"/api/v1/users/{other_user.id}", headers=headers)
    assert cross_org.status_code == 404


@pytest.mark.asyncio
async def test_user_list_hydrates_only_effective_permission_codes(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    organization = await make_organization(db_session)
    actor = await make_user_with_permissions(
        db_session,
        organization=organization,
        permissions=["users.read"],
    )
    target = await make_user_with_permissions(
        db_session,
        organization=organization,
        permissions=["organizations.read"],
        email="permissions@example.com",
    )
    expired_link = await db_session.scalar(
        select(MembershipRole).where(
            MembershipRole.membership_id == target._test_membership_id,  # type: ignore[attr-defined]
        )
    )
    assert expired_link is not None
    now = datetime.now(UTC)
    expired_link.assigned_at = now - timedelta(seconds=2)
    expired_link.expires_at = now - timedelta(seconds=1)
    await db_session.commit()

    response = await client.get(
        "/api/v1/users",
        headers=await auth_header_for(actor),
    )

    assert response.status_code == 200, response.text
    by_id = {row["id"]: row for row in response.json()["items"]}
    assert by_id[str(actor.id)]["permission_codes"] == ["users.read"]
    assert by_id[str(target.id)]["permission_codes"] == []


@pytest.mark.asyncio
async def test_rbac_assignment_lists_and_records_actor_membership(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    organization = await make_organization(db_session)
    actor = await make_user_with_permissions(
        db_session,
        organization=organization,
        permissions=["roles.create", "roles.read", "roles.update"],
    )
    target = await make_user_with_permissions(
        db_session,
        organization=organization,
        email="rbac-target@example.com",
    )
    permission = Permission(
        code="test.provenance",
        name="Test provenance",
        module="test",
    )
    db_session.add(permission)
    await db_session.commit()
    headers = await auth_header_for(actor)

    role_response = await client.post(
        "/api/v1/roles",
        headers=headers,
        json={"code": "auditor", "name": "Auditor", "permission_ids": []},
    )
    assert role_response.status_code == 201, role_response.text
    role_id = role_response.json()["id"]

    role_permission_response = await client.post(
        "/api/v1/role-permissions",
        headers=headers,
        json={"role_id": role_id, "permission_id": str(permission.id)},
    )
    assert role_permission_response.status_code == 201, role_permission_response.text
    role_permission = await db_session.get(
        RolePermission,
        role_permission_response.json()["id"],
    )
    assert role_permission is not None
    assert role_permission.granted_by_membership_id == actor._test_membership_id  # type: ignore[attr-defined]

    membership_role_response = await client.post(
        "/api/v1/membership-roles",
        headers=headers,
        json={
            "membership_id": str(target._test_membership_id),  # type: ignore[attr-defined]
            "role_id": role_id,
        },
    )
    assert membership_role_response.status_code == 201, membership_role_response.text
    membership_role = await db_session.get(
        MembershipRole,
        membership_role_response.json()["id"],
    )
    assert membership_role is not None
    assert membership_role.assigned_by_membership_id == actor._test_membership_id  # type: ignore[attr-defined]

    listed = await client.get("/api/v1/membership-roles", headers=headers)
    assert listed.status_code == 200, listed.text
