import uuid
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.foundation_enums import MembershipStatus, UserStatus
from src.modules.audit_logs.service import record_audit_log
from src.modules.auth import security
from src.modules.memberships.models import OrganizationMembership
from src.modules.rbac.models import MembershipRole, Permission, Role, RolePermission
from src.modules.users.exceptions import UserIdentifierConflict, UserNotFound
from src.modules.users.models import User
from src.modules.users.schemas import UserCreate, UserFilters, UserProfileUpdate
from src.pagination import Page, PaginationParams, paginate
from src.query_filters import SortSpec, apply_sort, search_clause

USER_SORT_COLUMNS = {
    "name": User.name,
    "email": User.email,
    "created_at": User.created_at,
    "last_login_at": User.last_login_at,
    "id": User.id,
}


async def get_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.get(User, user_id)


async def get_scoped_by_id(
    db: AsyncSession,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
) -> User | None:
    return await db.scalar(
        select(User)
        .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
        .where(
            User.id == user_id,
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.status != MembershipStatus.REMOVED,
        )
    )


async def find_for_login(db: AsyncSession, identifier: str) -> User | None:
    return await db.scalar(
        select(User).where(
            or_(func.lower(User.email) == identifier.casefold(), User.phone == identifier)
        )
    )


async def list_users(
    db: AsyncSession,
    organization_id: uuid.UUID,
    pagination: PaginationParams,
    filters: UserFilters,
    sort: tuple[SortSpec, ...],
) -> Page[User]:
    # Users visible through active memberships in this organization
    stmt = (
        select(User)
        .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
        .where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.status != MembershipStatus.REMOVED,
        )
    )
    stmt = _apply_filters(stmt, filters)
    stmt = apply_sort(stmt, sort, USER_SORT_COLUMNS)
    count_stmt = (
        select(func.count(User.id))
        .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
        .where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.status != MembershipStatus.REMOVED,
        )
    )
    count_stmt = _apply_filters(count_stmt, filters)
    page = await paginate(db, stmt, count_stmt, pagination)
    await attach_permission_codes(db, page.items, organization_id=organization_id)
    return page


async def create(
    db: AsyncSession,
    organization_id: uuid.UUID,
    data: UserCreate,
    *,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID | None,
) -> User:
    await _ensure_identifier_available(db, data.email, data.phone)
    user = User(
        name=data.name,
        email=data.email,
        phone=data.phone,
        password_hash=security.hash_password(data.password),
        status=UserStatus.ACTIVE,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise UserIdentifierConflict() from exc
    membership = OrganizationMembership(
        organization_id=organization_id,
        user_id=user.id,
        status=MembershipStatus.ACTIVE,
        joined_at=func_now(),
        activated_at=func_now(),
    )
    db.add(membership)
    await db.flush()
    if data.role_ids:
        await _replace_membership_roles(
            db,
            organization_id,
            membership.id,
            data.role_ids,
            actor_membership_id=actor_membership_id,
        )
    await record_audit_log(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        actor_membership_id=actor_membership_id,
        action="users.create",
        entity_type="user",
        entity_id=user.id,
        after_json=_loggable(user),
    )
    await db.commit()
    await db.refresh(user)
    return user


def func_now():
    from datetime import UTC, datetime

    return datetime.now(UTC)


async def update_profile(db: AsyncSession, user_id: uuid.UUID, data: UserProfileUpdate) -> User:
    user = await get_by_id(db, user_id)
    if user is None:
        raise UserNotFound()
    fields = data.model_dump(exclude_unset=True)
    await _ensure_identifier_available(
        db,
        fields.get("email", user.email),
        fields.get("phone", user.phone),
        exclude_user_id=user.id,
    )
    for key, value in fields.items():
        setattr(user, key, value)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise UserIdentifierConflict() from exc
    await db.commit()
    await db.refresh(user)
    return user


async def attach_permission_codes(
    db: AsyncSession,
    users: list[User],
    *,
    organization_id: uuid.UUID,
) -> None:
    if not users:
        return
    user_ids = [u.id for u in users]
    rows = await db.execute(
        select(OrganizationMembership.user_id, Permission.code)
        .join(MembershipRole, MembershipRole.membership_id == OrganizationMembership.id)
        .join(Role, Role.id == MembershipRole.role_id)
        .join(RolePermission, RolePermission.role_id == Role.id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id.in_(user_ids),
            MembershipRole.organization_id == organization_id,
            RolePermission.organization_id == organization_id,
            Role.organization_id == organization_id,
            or_(MembershipRole.expires_at.is_(None), MembershipRole.expires_at > func.now()),
            Role.is_active.is_(True),
            Permission.is_active.is_(True),
        )
    )
    by_user: dict[uuid.UUID, set[str]] = {uid: set() for uid in user_ids}
    for user_id, code in rows.all():
        by_user[user_id].add(code)
    for user in users:
        user.permission_codes = sorted(by_user.get(user.id, set()))  # type: ignore[attr-defined]


async def _ensure_identifier_available(
    db: AsyncSession,
    email: str | None,
    phone: str | None,
    *,
    exclude_user_id: uuid.UUID | None = None,
) -> None:
    if email:
        stmt = select(User.id).where(func.lower(User.email) == str(email).casefold())
        if exclude_user_id:
            stmt = stmt.where(User.id != exclude_user_id)
        if await db.scalar(stmt) is not None:
            raise UserIdentifierConflict()
    if phone:
        stmt = select(User.id).where(User.phone == phone)
        if exclude_user_id:
            stmt = stmt.where(User.id != exclude_user_id)
        if await db.scalar(stmt) is not None:
            raise UserIdentifierConflict()


async def _replace_membership_roles(
    db: AsyncSession,
    organization_id: uuid.UUID,
    membership_id: uuid.UUID,
    role_ids: list[uuid.UUID],
    *,
    actor_membership_id: uuid.UUID | None,
) -> None:
    existing = (
        await db.scalars(
            select(MembershipRole).where(
                MembershipRole.organization_id == organization_id,
                MembershipRole.membership_id == membership_id,
            )
        )
    ).all()
    for row in existing:
        await db.delete(row)
    for role_id in role_ids:
        role = await db.get(Role, role_id)
        if role is None or role.organization_id != organization_id:
            from src.modules.users.exceptions import InvalidRole

            raise InvalidRole()
        db.add(
            MembershipRole(
                organization_id=organization_id,
                membership_id=membership_id,
                role_id=role_id,
                assigned_by_membership_id=actor_membership_id,
            )
        )
    await db.flush()


def _apply_filters[StmtT: Select[Any]](stmt: StmtT, filters: UserFilters) -> StmtT:
    if filters.search:
        clause = search_clause([User.name, User.email, User.phone], filters.search)
        if clause is not None:
            stmt = stmt.where(clause)
    if filters.status is not None:
        stmt = stmt.where(User.status == filters.status)
    return stmt


def _loggable(user: User) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "phone": user.phone,
        "status": user.status.value,
    }
