from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.foundation_enums import UserStatus
from src.modules.auth import security
from src.modules.auth.models import UserRefreshToken
from src.modules.rbac.constants import (
    FOUNDATION_PERMISSION_MODULES,
    MODULE_EXTRA_ACTIONS,
    OWNER_ROLE_CODE,
    ActionType,
    extra_permission_code,
)
from src.modules.rbac.models import Role
from src.modules.users.models import UserRole

from tests.conftest import auth_headers, make_tenant, make_user_with_permissions, user_access_token


async def test_user_login_succeeds_with_tenant_code(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="demo")
    user = await make_user_with_permissions(db_session, tenant=tenant, email="owner@example.com")

    response = await client.post(
        "/api/v1/auth/login",
        json={
            "tenant_code": tenant.code,
            "identifier": user.email,
            "password": "Password123!",
        },
    )

    assert response.status_code == 200
    body = response.json()
    payload = security.decode_access_token(body["access_token"])
    assert payload["sub"] == str(user.id)
    assert payload["tenant_id"] == str(tenant.id)
    assert body["refresh_token"]


async def test_login_accepts_phone_identifier(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="shop")
    await make_user_with_permissions(db_session, tenant=tenant, phone="09123456789")

    response = await client.post(
        "/api/v1/auth/login",
        json={
            "tenant_code": tenant.code,
            "identifier": "09123456789",
            "password": "Password123!",
        },
    )

    assert response.status_code == 200


async def test_login_rejects_inactive_user(client: AsyncClient, db_session: AsyncSession) -> None:
    tenant = await make_tenant(db_session, code="inactive")
    user = await make_user_with_permissions(db_session, tenant=tenant, email="inactive@example.com")
    user.status = UserStatus.LOCKED
    await db_session.flush()

    response = await client.post(
        "/api/v1/auth/login",
        json={
            "tenant_code": tenant.code,
            "identifier": user.email,
            "password": "Password123!",
        },
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "inactive_user"


async def test_get_me_includes_owner_permission_codes(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="owner-me")
    user = await make_user_with_permissions(db_session, tenant=tenant, email="me@example.com")
    owner_role = Role(
        tenant_id=tenant.id,
        code=OWNER_ROLE_CODE,
        name="Owner",
        is_system=True,
    )
    db_session.add(owner_role)
    await db_session.flush()
    db_session.add(UserRole(tenant_id=tenant.id, user_id=user.id, role_id=owner_role.id))
    await db_session.flush()

    response = await client.get(
        "/api/v1/auth/me",
        headers=auth_headers(user_access_token(user)),
    )

    assert response.status_code == 200
    permission_codes = set(response.json()["permission_codes"])
    assert permission_codes == {
        f"{module}.{action.value}"
        for module in FOUNDATION_PERMISSION_MODULES
        for action in ActionType
    } | {
        extra_permission_code(module, extra_action)
        for module, extra_actions in MODULE_EXTRA_ACTIONS.items()
        for extra_action in extra_actions
    }


async def test_refresh_rotates_and_logout_revokes(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="tokens")
    user = await make_user_with_permissions(db_session, tenant=tenant, email="tokens@example.com")
    login_response = await client.post(
        "/api/v1/auth/login",
        json={
            "tenant_code": tenant.code,
            "identifier": user.email,
            "password": "Password123!",
        },
    )
    refresh_token = login_response.json()["refresh_token"]

    rotated = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert rotated.status_code == 200
    reused = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert reused.status_code == 401

    await client.post("/api/v1/auth/logout", headers=auth_headers(rotated.json()["access_token"]))
    revoked = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": rotated.json()["refresh_token"]},
    )
    assert revoked.status_code == 401


async def test_change_password_revokes_refresh_tokens(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="passwords")
    user = await make_user_with_permissions(
        db_session, tenant=tenant, email="passwords@example.com"
    )
    login_response = await client.post(
        "/api/v1/auth/login",
        json={
            "tenant_code": tenant.code,
            "identifier": user.email,
            "password": "Password123!",
        },
    )

    response = await client.patch(
        "/api/v1/auth/me/change-password",
        json={"current_password": "Password123!", "new_password": "NewPassword456!"},
        headers=auth_headers(user_access_token(user)),
    )

    assert response.status_code == 204
    token_hash = security.hash_refresh_token(login_response.json()["refresh_token"])
    stored = await db_session.scalar(
        select(UserRefreshToken).where(UserRefreshToken.token_hash == token_hash)
    )
    assert stored is not None
    assert stored.revoked_at is not None
