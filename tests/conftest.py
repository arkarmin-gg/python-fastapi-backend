import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest_asyncio
import src.registry  # noqa: F401
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from src.database import engine, get_db
from src.foundation_enums import MembershipStatus
from src.main import create_app
from src.models import Base
from src.modules.auth import security
from src.modules.memberships.models import OrganizationMembership
from src.modules.organizations.models import Organization
from src.modules.rbac.models import MembershipRole, Permission, Role, RolePermission
from src.modules.users.models import User
from src.modules.users.normalize import normalize_email


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    connection = await engine.connect()
    schema_name = f"test_{uuid.uuid4().hex}"
    quoted_schema = f'"{schema_name}"'
    await connection.execute(text(f"CREATE SCHEMA {quoted_schema}"))
    await connection.execute(text(f"SET search_path TO {quoted_schema}, public"))
    await connection.run_sync(
        lambda sync_conn: Base.metadata.create_all(sync_conn, checkfirst=False)
    )
    await connection.commit()

    outer_transaction = await connection.begin()
    session_factory = async_sessionmaker(
        bind=connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )
    session = session_factory()
    try:
        yield session
    finally:
        await session.close()
        await outer_transaction.rollback()
        await connection.execute(text(f"DROP SCHEMA {quoted_schema} CASCADE"))
        await connection.commit()
        await connection.close()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


async def make_organization(db_session: AsyncSession, *, code: str | None = None) -> Organization:
    org = Organization(
        code=code or f"org-{uuid.uuid4().hex[:8]}",
        name="Test Organization",
    )
    db_session.add(org)
    await db_session.flush()
    return org


async def _ensure_permission(db_session: AsyncSession, code: str) -> Permission:
    from sqlalchemy import select

    permission = await db_session.scalar(select(Permission).where(Permission.code == code))
    if permission is None:
        module, _, _action = code.partition(".")
        permission = Permission(
            code=code,
            name=code,
            module=module or "misc",
            description=code,
        )
        db_session.add(permission)
        await db_session.flush()
    return permission


async def make_user_with_permissions(
    db_session: AsyncSession,
    *,
    organization: Organization | None = None,
    permissions: list[str] | None = None,
    email: str | None = None,
    phone: str | None = None,
    password: str = "Password123!",
) -> User:

    organization = organization or await make_organization(db_session)
    permission_codes = permissions or []
    role = Role(
        organization_id=organization.id,
        code=f"role-{uuid.uuid4().hex[:8]}",
        name="Test Role",
    )
    db_session.add(role)
    await db_session.flush()

    for code in permission_codes:
        permission = await _ensure_permission(db_session, code)
        db_session.add(
            RolePermission(
                organization_id=organization.id,
                role_id=role.id,
                permission_id=permission.id,
            )
        )

    email_value = email or f"user-{uuid.uuid4().hex[:8]}@example.com"
    user = User(
        name="Test User",
        email=email_value,
        email_normalized=normalize_email(email_value),
        phone=phone,
        password_hash=security.hash_password(password),
    )
    db_session.add(user)
    await db_session.flush()

    now = datetime.now(UTC)
    membership = OrganizationMembership(
        organization_id=organization.id,
        user_id=user.id,
        status=MembershipStatus.ACTIVE,
        joined_at=now,
        activated_at=now,
    )
    db_session.add(membership)
    await db_session.flush()
    db_session.add(
        MembershipRole(
            organization_id=organization.id,
            membership_id=membership.id,
            role_id=role.id,
        )
    )
    await db_session.flush()
    # stash for tests
    user._test_organization_id = organization.id  # type: ignore[attr-defined]
    user._test_membership_id = membership.id  # type: ignore[attr-defined]
    user._test_organization_code = organization.code  # type: ignore[attr-defined]
    return user


async def auth_header_for(user: User) -> dict[str, str]:
    token = security.create_access_token(
        str(user.id),
        str(user._test_organization_id),  # type: ignore[attr-defined]
        str(user._test_membership_id),  # type: ignore[attr-defined]
    )
    return {"Authorization": f"Bearer {token}"}
