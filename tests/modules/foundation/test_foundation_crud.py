import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

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
    assert "acme" in codes


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
