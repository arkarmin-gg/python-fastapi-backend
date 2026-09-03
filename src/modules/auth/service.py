import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.exceptions import InvalidCredentials, InvalidCurrentPassword, InvalidToken
from src.foundation_enums import TenantStatus, UserStatus
from src.modules.auth import security
from src.modules.auth.config import auth_settings
from src.modules.auth.exceptions import InactiveUser
from src.modules.auth.models import UserRefreshToken
from src.modules.tenants import service as tenant_service
from src.modules.users import service as user_service
from src.modules.users.models import User


async def authenticate_user(
    db: AsyncSession,
    *,
    tenant_id: str | None,
    tenant_code: str | None,
    identifier: str,
    password: str,
) -> User:
    tenant = None
    if tenant_id is not None:
        try:
            tenant_uuid = uuid.UUID(tenant_id)
        except ValueError as exc:
            raise InvalidCredentials() from exc
        tenant = await tenant_service.get_by_id(db, tenant_uuid)
    elif tenant_code is not None:
        tenant = await tenant_service.get_by_code(db, tenant_code)
    if tenant is None or tenant.status != TenantStatus.ACTIVE:
        raise InvalidCredentials()

    user = await user_service.find_for_login(db, tenant.id, identifier)
    if user is None or not security.verify_password(password, user.password_hash):
        raise InvalidCredentials()
    if user.status != UserStatus.ACTIVE:
        raise InactiveUser()
    return user


async def login(
    db: AsyncSession,
    *,
    tenant_id: str | None,
    tenant_code: str | None,
    identifier: str,
    password: str,
) -> tuple[str, str]:
    user = await authenticate_user(
        db,
        tenant_id=tenant_id,
        tenant_code=tenant_code,
        identifier=identifier,
        password=password,
    )
    access_token = security.create_access_token(str(user.id), str(user.tenant_id))
    refresh_token = await _issue_refresh_token(db, user)
    user.last_login_at = datetime.now(UTC)
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
        or stored.user_id is None
        or (stored.expires_at is not None and stored.expires_at < now)
    ):
        raise InvalidToken()

    user = await user_service.get_by_id(db, stored.tenant_id, stored.user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        raise InvalidToken()

    stored.revoked_at = now
    access_token = security.create_access_token(str(user.id), str(user.tenant_id))
    refresh_token = await _issue_refresh_token(db, user)
    await db.commit()
    return access_token, refresh_token


async def logout(db: AsyncSession, user: User) -> None:
    now = datetime.now(UTC)
    await db.execute(
        update(UserRefreshToken)
        .where(UserRefreshToken.user_id == user.id, UserRefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    user.last_logout_at = now
    await db.commit()


async def change_password(
    db: AsyncSession,
    user: User,
    current_password: str,
    new_password: str,
) -> None:
    if not security.verify_password(current_password, user.password_hash):
        raise InvalidCurrentPassword()
    user.password_hash = security.hash_password(new_password)
    await db.execute(
        update(UserRefreshToken)
        .where(UserRefreshToken.user_id == user.id, UserRefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    await db.commit()


async def _issue_refresh_token(db: AsyncSession, user: User) -> str:
    raw = security.generate_refresh_token()
    db.add(
        UserRefreshToken(
            token_hash=security.hash_refresh_token(raw),
            tenant_id=user.tenant_id,
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(days=auth_settings.REFRESH_TOKEN_EXP_DAYS),
        )
    )
    return raw
