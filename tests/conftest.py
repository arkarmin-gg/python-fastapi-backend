import uuid
from collections.abc import AsyncIterator

import pytest_asyncio
import src.registry  # noqa: F401
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from src.database import engine, get_db
from src.main import create_app
from src.models import Base
from src.modules.auth import security
from src.modules.rbac.constants import ActionType, permission_code
from src.modules.rbac.models import Permission, Role, RolePermission
from src.modules.tenants.models import Tenant
from src.modules.users.models import User, UserRole


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
async def concurrent_sessions() -> AsyncIterator[tuple[AsyncSession, AsyncSession]]:
    """Two independent DB sessions on separate connections sharing one schema.

    Unlike `db_session`, each session here has its own real connection and
    transaction, so `SELECT ... FOR UPDATE` row locks taken by one session
    actually block the other. Use this for tests that need to prove a race
    condition is closed, not just that a sequential status check works.
    """
    schema_name = f"test_{uuid.uuid4().hex}"
    quoted_schema = f'"{schema_name}"'
    setup_connection = await engine.connect()
    await setup_connection.execute(text(f"CREATE SCHEMA {quoted_schema}"))
    await setup_connection.execute(text(f"SET search_path TO {quoted_schema}, public"))
    await setup_connection.run_sync(
        lambda sync_conn: Base.metadata.create_all(sync_conn, checkfirst=False)
    )
    await setup_connection.commit()
    await setup_connection.close()

    # Each session sets its own search_path as its FIRST statement (rather than
    # via the raw connection before binding a session). Pre-executing on the raw
    # connection would autobegin an ambient transaction, causing the session's
    # default join_transaction_mode to nest inside it as a savepoint — so
    # session.commit() would only release the savepoint, never truly committing,
    # leaving other connections unable to see the "committed" rows at all.
    connection_a = await engine.connect()
    connection_b = await engine.connect()
    session_a = async_sessionmaker(bind=connection_a, expire_on_commit=False)()
    session_b = async_sessionmaker(bind=connection_b, expire_on_commit=False)()
    await session_a.execute(text(f"SET search_path TO {quoted_schema}, public"))
    await session_b.execute(text(f"SET search_path TO {quoted_schema}, public"))
    try:
        yield session_a, session_b
    finally:
        await session_a.close()
        await session_b.close()
        await connection_a.close()
        await connection_b.close()
        cleanup_connection = await engine.connect()
        await cleanup_connection.execute(text(f"DROP SCHEMA {quoted_schema} CASCADE"))
        await cleanup_connection.commit()
        await cleanup_connection.close()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


async def make_tenant(db_session: AsyncSession, *, code: str | None = None) -> Tenant:
    tenant = Tenant(code=code or f"tenant-{uuid.uuid4().hex[:8]}", name="Test Tenant")
    db_session.add(tenant)
    await db_session.flush()
    return tenant


async def make_user_with_permissions(
    db_session: AsyncSession,
    *,
    tenant: Tenant | None = None,
    permissions: list[str] | None = None,
    email: str | None = None,
    phone: str | None = None,
    password: str = "Password123!",
) -> User:
    tenant = tenant or await make_tenant(db_session)
    permission_codes = permissions or []
    role = Role(
        tenant_id=tenant.id,
        code=f"role-{uuid.uuid4().hex[:8]}",
        name="Test Role",
    )
    db_session.add(role)
    await db_session.flush()

    for code in permission_codes:
        permission = await _ensure_permission(db_session, code)
        db_session.add(
            RolePermission(
                tenant_id=tenant.id,
                role_id=role.id,
                permission_id=permission.id,
            )
        )

    user = User(
        tenant_id=tenant.id,
        name="Test User",
        email=email or f"user-{uuid.uuid4().hex[:8]}@example.com",
        phone=phone,
        password_hash=security.hash_password(password),
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(UserRole(tenant_id=tenant.id, user_id=user.id, role_id=role.id))
    await db_session.flush()
    return user


async def _ensure_permission(db_session: AsyncSession, code: str) -> Permission:
    existing = await db_session.scalar(select(Permission).where(Permission.code == code))
    if existing is not None:
        return existing
    module, _, action = code.partition(".")
    permission = Permission(
        code=code,
        name=f"{module.title()} {action.title()}",
        module=module,
    )
    db_session.add(permission)
    await db_session.flush()
    return permission


def user_access_token(user: User) -> str:
    return security.create_access_token(str(user.id), str(user.tenant_id))


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def permission(module: str, action: ActionType) -> str:
    return permission_code(module, action)
