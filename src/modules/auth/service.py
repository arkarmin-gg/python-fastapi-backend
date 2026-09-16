import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.exceptions import InvalidCredentials, InvalidCurrentPassword, InvalidToken
from src.foundation_enums import MembershipStatus, OrganizationStatus, UserStatus
from src.modules.auth import security
from src.modules.auth.config import auth_settings
from src.modules.auth.exceptions import InactiveUser
from src.modules.auth.models import UserRefreshToken, UserSession
from src.modules.memberships.models import OrganizationMembership
from src.modules.organizations import service as organization_service
from src.modules.users import service as user_service
from src.modules.users.models import User


async def authenticate_user(
    db: AsyncSession,
    *,
    organization_id: str | None,
    organization_code: str | None,
    identifier: str,
    password: str,
) -> tuple[User, OrganizationMembership]:
    organization = None
    if organization_id is not None:
        try:
            organization_uuid = uuid.UUID(organization_id)
        except ValueError as exc:
            raise InvalidCredentials() from exc
        organization = await organization_service.get_by_id(db, organization_uuid)
    elif organization_code is not None:
        organization = await organization_service.get_by_code(db, organization_code)

    if organization is None or organization.status != OrganizationStatus.ACTIVE:
        raise InvalidCredentials()

    user = await user_service.find_for_login(db, identifier)
    if user is None or not security.verify_password(password, user.password_hash):
        raise InvalidCredentials()
    if user.status != UserStatus.ACTIVE:
        raise InactiveUser()

    membership = await db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization.id,
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.status == MembershipStatus.ACTIVE,
        )
    )
    if membership is None:
        raise InvalidCredentials()

    return user, membership


async def login(
    db: AsyncSession,
    *,
    organization_id: str | None,
    organization_code: str | None,
    identifier: str,
    password: str,
) -> tuple[str, str]:
    user, membership = await authenticate_user(
        db,
        organization_id=organization_id,
        organization_code=organization_code,
        identifier=identifier,
        password=password,
    )
    user.last_login_at = datetime.now(UTC)
    access_token = security.create_access_token(
        str(user.id),
        str(membership.organization_id),
        str(membership.id),
    )
    refresh_token = await _issue_refresh_token(db, user)
    await db.commit()
    return access_token, refresh_token


async def rotate_refresh_token(db: AsyncSession, raw_token: str) -> tuple[str, str]:
    token_hash = security.hash_refresh_token(raw_token)
    stored = await db.scalar(
        select(UserRefreshToken).where(UserRefreshToken.token_hash == token_hash)
    )
    now = datetime.now(UTC)
    if (
        stored is None
        or stored.revoked_at is not None
        or stored.expires_at <= now
        or stored.used_at is not None
    ):
        if stored is not None and stored.used_at is not None:
            # reuse detection — revoke session family
            await db.execute(
                update(UserSession)
                .where(UserSession.id == stored.session_id)
                .values(revoked_at=now, revoke_reason="refresh_reuse")
            )
            await db.execute(
                update(UserRefreshToken)
                .where(UserRefreshToken.session_id == stored.session_id)
                .values(revoked_at=now, revoke_reason="refresh_reuse")
            )
            await db.commit()
        raise InvalidToken()

    user = await user_service.get_by_id(db, stored.user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        raise InvalidToken()

    # Need organization context — take an active membership for this user.
    # Prefer keeping prior org by looking at session... JWT not available on refresh.
    # Store organization on session? DBML sessions are global. Client must send org on next access.
    # For refresh we re-issue access using the user's first active membership.
    membership = await db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.status == MembershipStatus.ACTIVE,
        )
    )
    if membership is None:
        raise InvalidToken()

    stored.used_at = now
    new_raw = await _issue_refresh_token(
        db, user, session_id=stored.session_id, parent_token_id=stored.id
    )
    # link replaced_by
    new_hash = security.hash_refresh_token(new_raw)
    new_row = await db.scalar(
        select(UserRefreshToken).where(UserRefreshToken.token_hash == new_hash)
    )
    if new_row is not None:
        stored.replaced_by_token_id = new_row.id

    access_token = security.create_access_token(
        str(user.id),
        str(membership.organization_id),
        str(membership.id),
    )
    await db.commit()
    return access_token, new_raw


async def logout(db: AsyncSession, user: User) -> None:
    now = datetime.now(UTC)
    user.last_logout_at = now
    await db.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .values(revoked_at=now, revoke_reason="logout")
    )
    await db.execute(
        update(UserRefreshToken)
        .where(UserRefreshToken.user_id == user.id, UserRefreshToken.revoked_at.is_(None))
        .values(revoked_at=now, revoke_reason="logout")
    )
    await db.commit()


async def change_password(
    db: AsyncSession,
    user: User,
    *,
    current_password: str,
    new_password: str,
) -> None:
    if not security.verify_password(current_password, user.password_hash):
        raise InvalidCurrentPassword()
    user.password_hash = security.hash_password(new_password)
    user.password_changed_at = datetime.now(UTC)
    await logout(db, user)


async def _issue_refresh_token(
    db: AsyncSession,
    user: User,
    *,
    session_id: uuid.UUID | None = None,
    parent_token_id: uuid.UUID | None = None,
) -> str:
    now = datetime.now(UTC)
    expires = now + timedelta(days=auth_settings.REFRESH_TOKEN_EXP_DAYS)
    if session_id is None:
        session = UserSession(user_id=user.id, expires_at=expires, last_seen_at=now)
        db.add(session)
        await db.flush()
        session_id = session.id

    raw = security.generate_refresh_token()
    db.add(
        UserRefreshToken(
            user_id=user.id,
            session_id=session_id,
            token_hash=security.hash_refresh_token(raw),
            parent_token_id=parent_token_id,
            expires_at=expires,
        )
    )
    await db.flush()
    return raw
