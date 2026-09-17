from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.foundation_enums import MembershipStatus
from src.modules.audit_logs.models import AuditLog
from src.modules.auth import security
from src.modules.auth.models import UserRefreshToken, UserSession
from src.modules.memberships.models import OrganizationMembership

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
        headers={"X-Request-ID": "login-request", "X-Trace-ID": "login-trace"},
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
        json={"refresh_token": body["refresh_token"], "organization_code": "demo"},
    )
    assert refreshed.status_code == 200, refreshed.text
    assert "access_token" in refreshed.json()
    refreshed_claims = security.decode_access_token(refreshed.json()["access_token"])
    assert str(org.id) == refreshed_claims["organization_id"]

    logout = await client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {refreshed.json()['access_token']}"},
    )
    assert logout.status_code == 204
    auth_logs = (
        await db_session.scalars(
            select(AuditLog).where(
                AuditLog.organization_id == org.id,
                AuditLog.actor_user_id.is_not(None),
            )
        )
    ).all()
    assert {"auth.login", "auth.refresh", "auth.logout"} <= {
        audit_log.action for audit_log in auth_logs
    }
    login_log = next(log for log in auth_logs if log.action == "auth.login")
    assert login_log.request_id == "login-request"
    assert login_log.trace_id == "login-trace"


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


@pytest.mark.asyncio
async def test_refresh_requires_organization_context(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "opaque"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("session_state", ["revoked", "expired"])
async def test_refresh_rejects_inactive_session(
    client: AsyncClient,
    db_session: AsyncSession,
    session_state: str,
) -> None:
    org = await make_organization(db_session)
    user = await make_user_with_permissions(
        db_session,
        organization=org,
        email=f"{session_state}@example.com",
    )
    await db_session.commit()
    login = await client.post(
        "/api/v1/auth/login",
        json={
            "organization_id": str(org.id),
            "identifier": user.email,
            "password": "Password123!",
        },
    )
    assert login.status_code == 200, login.text
    refresh_token = login.json()["refresh_token"]
    stored = await db_session.scalar(
        select(UserRefreshToken).where(
            UserRefreshToken.token_hash == security.hash_refresh_token(refresh_token)
        )
    )
    assert stored is not None
    session = await db_session.get(UserSession, stored.session_id)
    assert session is not None
    if session_state == "revoked":
        session.revoked_at = datetime.now(UTC)
        session.revoke_reason = "test"
    else:
        now = datetime.now(UTC)
        session.created_at = now - timedelta(seconds=2)
        session.expires_at = now - timedelta(seconds=1)
    await db_session.commit()

    response = await client.post(
        "/api/v1/auth/refresh",
        json={
            "refresh_token": refresh_token,
            "organization_id": str(org.id),
        },
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_selects_requested_active_membership(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    first_org = await make_organization(db_session)
    second_org = await make_organization(db_session)
    user = await make_user_with_permissions(
        db_session,
        organization=first_org,
        email="multi-org@example.com",
    )
    second_membership = OrganizationMembership(
        organization_id=second_org.id,
        user_id=user.id,
        status=MembershipStatus.ACTIVE,
        joined_at=datetime.now(UTC),
        activated_at=datetime.now(UTC),
    )
    db_session.add(second_membership)
    await db_session.commit()
    login = await client.post(
        "/api/v1/auth/login",
        json={
            "organization_id": str(first_org.id),
            "identifier": user.email,
            "password": "Password123!",
        },
    )
    assert login.status_code == 200, login.text

    response = await client.post(
        "/api/v1/auth/refresh",
        json={
            "refresh_token": login.json()["refresh_token"],
            "organization_id": str(second_org.id),
        },
    )

    assert response.status_code == 200, response.text
    claims = security.decode_access_token(response.json()["access_token"])
    assert str(second_org.id) == claims["organization_id"]
    assert str(second_membership.id) == claims["membership_id"]


@pytest.mark.asyncio
async def test_refresh_reuse_revokes_session_family_and_caps_child_expiry(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org = await make_organization(db_session)
    user = await make_user_with_permissions(
        db_session,
        organization=org,
        email="reuse@example.com",
    )
    await db_session.commit()
    login = await client.post(
        "/api/v1/auth/login",
        json={
            "organization_id": str(org.id),
            "identifier": user.email,
            "password": "Password123!",
        },
    )
    assert login.status_code == 200, login.text
    original_raw = login.json()["refresh_token"]
    original = await db_session.scalar(
        select(UserRefreshToken).where(
            UserRefreshToken.token_hash == security.hash_refresh_token(original_raw)
        )
    )
    assert original is not None
    session = await db_session.get(UserSession, original.session_id)
    assert session is not None
    session.expires_at = datetime.now(UTC) + timedelta(minutes=5)
    await db_session.commit()

    first_refresh = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": original_raw, "organization_id": str(org.id)},
    )
    assert first_refresh.status_code == 200, first_refresh.text
    child_raw = first_refresh.json()["refresh_token"]
    child = await db_session.scalar(
        select(UserRefreshToken).where(
            UserRefreshToken.token_hash == security.hash_refresh_token(child_raw)
        )
    )
    assert child is not None
    assert child.expires_at <= session.expires_at

    reused = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": original_raw, "organization_id": str(org.id)},
    )
    assert reused.status_code == 401
    await db_session.refresh(session)
    await db_session.refresh(child)
    assert session.revoke_reason == "refresh_reuse"
    assert child.revoke_reason == "refresh_reuse"
