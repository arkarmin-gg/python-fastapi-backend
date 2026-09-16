import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import make_organization, make_user_with_permissions


@pytest.mark.asyncio
async def test_login_refresh_logout(client: AsyncClient, db_session: AsyncSession) -> None:
    org = await make_organization(db_session, code="demo")
    await make_user_with_permissions(
        db_session,
        organization=org,
        email="owner@example.com",
        password="Password123!",
        permissions=["organizations.read"],
    )
    await db_session.commit()

    login = await client.post(
        "/api/v1/auth/login",
        json={
            "organization_code": "demo",
            "identifier": "owner@example.com",
            "password": "Password123!",
        },
    )
    assert login.status_code == 200, login.text
    body = login.json()
    assert "access_token" in body
    assert "refresh_token" in body

    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == "owner@example.com"

    refreshed = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": body["refresh_token"]},
    )
    assert refreshed.status_code == 200, refreshed.text
    assert "access_token" in refreshed.json()

    logout = await client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {refreshed.json()['access_token']}"},
    )
    assert logout.status_code == 204


@pytest.mark.asyncio
async def test_login_rejects_wrong_password(client: AsyncClient, db_session: AsyncSession) -> None:
    org = await make_organization(db_session, code="demo2")
    await make_user_with_permissions(
        db_session,
        organization=org,
        email="owner2@example.com",
        password="Password123!",
    )
    await db_session.commit()

    response = await client.post(
        "/api/v1/auth/login",
        json={
            "organization_code": "demo2",
            "identifier": "owner2@example.com",
            "password": "wrong-password",
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_requires_auth(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401
