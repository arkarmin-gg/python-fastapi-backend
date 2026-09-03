import uuid
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.foundation_enums import UserStatus
from src.modules.audit_logs.service import record_audit_log
from src.modules.auth import security
from src.modules.employees.models import Employee
from src.modules.rbac.constants import (
    FOUNDATION_PERMISSION_MODULES,
    MODULE_EXTRA_ACTIONS,
    OWNER_ROLE_CODE,
    ActionType,
    extra_permission_code,
    permission_code,
)
from src.modules.rbac.models import Permission, Role, RolePermission
from src.modules.users.exceptions import (
    InvalidEmployee,
    InvalidRole,
    SelfDeactivateConflict,
    UserIdentifierConflict,
    UserNotFound,
)
from src.modules.users.models import User, UserRole
from src.modules.users.schemas import UserCreate, UserFilters, UserProfileUpdate, UserUpdate
from src.pagination import Page, PaginationParams, paginate
from src.query_filters import SortSpec, apply_sort, search_clause

USER_SORT_COLUMNS = {
    "name": User.name,
    "email": User.email,
    "created_at": User.created_at,
    "last_login_at": User.last_login_at,
    "id": User.id,
}


async def get_by_id(db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID) -> User | None:
    result = await db.execute(
        select(User)
        .where(User.tenant_id == tenant_id, User.id == user_id)
        .options(selectinload(User.role_links))
    )
    user = result.scalar_one_or_none()
    if user is not None:
        await attach_permission_codes(db, [user])
    return user


async def find_for_login(db: AsyncSession, tenant_id: uuid.UUID, identifier: str) -> User | None:
    result = await db.execute(
        select(User)
        .where(
            User.tenant_id == tenant_id,
            or_(User.email == identifier, User.phone == identifier),
        )
        .options(selectinload(User.role_links))
    )
    return result.scalar_one_or_none()


async def list_users(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: UserFilters,
    sort: tuple[SortSpec, ...],
) -> Page[User]:
    stmt = _apply_filters(select(User).where(User.tenant_id == tenant_id), filters).options(
        selectinload(User.role_links)
    )
    stmt = apply_sort(stmt, sort, USER_SORT_COLUMNS)
    count_stmt = _apply_filters(
        select(func.count(User.id)).where(User.tenant_id == tenant_id), filters
    )
    page = await paginate(db, stmt, count_stmt, pagination)
    await attach_permission_codes(db, page.items)
    return page


async def create(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: UserCreate,
    *,
    actor_user_id: uuid.UUID,
) -> User:
    await _ensure_identifier_available(db, tenant_id, data.email)
    await _ensure_employee(db, tenant_id, data.employee_id)
    await _ensure_roles(db, tenant_id, data.role_ids)
    fields = data.model_dump(exclude={"password", "role_ids"})
    user = User(tenant_id=tenant_id, password_hash=security.hash_password(data.password), **fields)
    db.add(user)
    await db.flush()
    await _replace_roles(db, user, data.role_ids)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="users.create",
        entity_type="user",
        entity_id=user.id,
        after_json=_loggable(user),
    )
    await db.commit()
    created = await get_by_id(db, tenant_id, user.id)
    if created is None:
        raise UserNotFound()
    return created


async def update(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    data: UserUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> User:
    user = await get_by_id(db, tenant_id, user_id)
    if user is None:
        raise UserNotFound()
    before = _loggable(user)
    fields = data.model_dump(exclude_unset=True, exclude={"password", "role_ids"})
    if "email" in fields and fields["email"] != user.email:
        await _ensure_identifier_available(db, tenant_id, fields["email"], user_id=user.id)
    if "employee_id" in fields:
        await _ensure_employee(db, tenant_id, fields["employee_id"])
    if data.role_ids is not None:
        await _ensure_roles(db, tenant_id, data.role_ids)
    for key, value in fields.items():
        setattr(user, key, value)
    if data.password is not None:
        user.password_hash = security.hash_password(data.password)
    if data.role_ids is not None:
        await _replace_roles(db, user, data.role_ids)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="users.update",
        entity_type="user",
        entity_id=user.id,
        before_json=before,
        after_json=_loggable(user),
    )
    await db.commit()
    updated = await get_by_id(db, tenant_id, user.id)
    if updated is None:
        raise UserNotFound()
    return updated


async def update_profile(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    data: UserProfileUpdate,
) -> User:
    user = await get_by_id(db, tenant_id, user_id)
    if user is None:
        raise UserNotFound()
    fields = data.model_dump(exclude_unset=True)
    if "email" in fields and fields["email"] != user.email:
        await _ensure_identifier_available(db, tenant_id, fields["email"], user_id=user.id)
    for key, value in fields.items():
        setattr(user, key, value)
    await db.commit()
    updated = await get_by_id(db, tenant_id, user.id)
    if updated is None:
        raise UserNotFound()
    return updated


async def attach_permission_codes(db: AsyncSession, users: list[User]) -> None:
    if not users:
        return

    user_ids = [user.id for user in users]
    codes_by_user_id: dict[uuid.UUID, set[str]] = {user.id: set() for user in users}
    owner_user_ids: set[uuid.UUID] = set()

    rows = (
        await db.execute(
            select(UserRole.user_id, Role.code, Permission.code)
            .join(Role, Role.id == UserRole.role_id)
            .outerjoin(
                RolePermission,
                (RolePermission.role_id == Role.id)
                & (RolePermission.tenant_id == UserRole.tenant_id),
            )
            .outerjoin(Permission, Permission.id == RolePermission.permission_id)
            .where(
                UserRole.user_id.in_(user_ids),
                UserRole.tenant_id.in_({user.tenant_id for user in users}),
                Role.is_active.is_(True),
            )
        )
    ).all()

    for user_id, role_code, db_permission_code in rows:
        if role_code == OWNER_ROLE_CODE:
            owner_user_ids.add(user_id)
        if db_permission_code is not None:
            codes_by_user_id[user_id].add(db_permission_code)

    owner_permission_codes = {
        permission_code(module, action)
        for module in FOUNDATION_PERMISSION_MODULES
        for action in ActionType
    } | {
        extra_permission_code(module, extra_action)
        for module, extra_actions in MODULE_EXTRA_ACTIONS.items()
        for extra_action in extra_actions
    }
    for user_id in owner_user_ids:
        codes_by_user_id[user_id].update(owner_permission_codes)

    for user in users:
        user.permission_codes = sorted(codes_by_user_id[user.id])


async def deactivate(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    # Check actor user cannot deactivate yourself
    if actor_user_id == user_id:
        raise SelfDeactivateConflict

    await update(
        db,
        tenant_id,
        user_id,
        UserUpdate(status=UserStatus.INACTIVE),
        actor_user_id=actor_user_id,
    )


async def _ensure_identifier_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    email: str | None,
    *,
    user_id: uuid.UUID | None = None,
) -> None:
    if email is None:
        return
    existing = await db.scalar(select(User).where(User.tenant_id == tenant_id, User.email == email))
    if existing is not None and existing.id != user_id:
        raise UserIdentifierConflict()


async def _ensure_employee(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    employee_id: uuid.UUID | None,
) -> None:
    if employee_id is None:
        return
    if (
        await db.scalar(
            select(Employee.id).where(Employee.tenant_id == tenant_id, Employee.id == employee_id)
        )
        is None
    ):
        raise InvalidEmployee()


async def _ensure_roles(db: AsyncSession, tenant_id: uuid.UUID, role_ids: list[uuid.UUID]) -> None:
    unique_role_ids = set(role_ids)
    if not unique_role_ids:
        return
    found = await db.scalar(
        select(func.count(Role.id)).where(Role.tenant_id == tenant_id, Role.id.in_(unique_role_ids))
    )
    if found != len(unique_role_ids):
        raise InvalidRole()


async def _replace_roles(db: AsyncSession, user: User, role_ids: list[uuid.UUID]) -> None:
    await db.refresh(user, attribute_names=["role_links"])
    new_role_ids = set(role_ids)
    existing_role_ids = {link.role_id for link in user.role_links}
    user.role_links = [link for link in user.role_links if link.role_id in new_role_ids] + [
        UserRole(tenant_id=user.tenant_id, user_id=user.id, role_id=role_id)
        for role_id in new_role_ids - existing_role_ids
    ]


def _apply_filters[StmtT: Select[Any]](stmt: StmtT, filters: UserFilters) -> StmtT:
    search = search_clause([User.name, User.email, User.phone], filters.search)
    if search is not None:
        stmt = stmt.where(search)
    if filters.status is not None:
        stmt = stmt.where(User.status == filters.status)
    return stmt


def _loggable(user: User) -> dict[str, Any]:
    return {
        "name": user.name,
        "email": user.email,
        "phone": user.phone,
        "status": user.status.value,
        "role_ids": [str(role_id) for role_id in user.role_ids],
    }
