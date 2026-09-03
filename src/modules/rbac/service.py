import uuid
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.foundation_enums import UserStatus
from src.modules.audit_logs.service import record_audit_log
from src.modules.rbac.exceptions import (
    InvalidPermission,
    InvalidRole,
    InvalidUser,
    ProtectedRole,
    RoleAssigned,
    RoleCodeConflict,
    RoleNotFound,
    RolePermissionConflict,
    RolePermissionNotFound,
    UserRoleConflict,
    UserRoleNotFound,
)
from src.modules.rbac.models import Permission, Role, RolePermission
from src.modules.rbac.schemas import (
    RoleCreate,
    RoleFilters,
    RolePermissionCreate,
    RolePermissionFilters,
    RoleUpdate,
    UserRoleCreate,
    UserRoleFilters,
)
from src.modules.users.models import User, UserRole
from src.pagination import Page, PaginationParams, paginate
from src.query_filters import SortSpec, apply_sort, search_clause

ROLE_SORT_COLUMNS = {
    "code": Role.code,
    "name": Role.name,
    "created_at": Role.created_at,
    "id": Role.id,
}
ROLE_PERMISSION_SORT_COLUMNS = {
    "role_id": RolePermission.role_id,
    "permission_id": RolePermission.permission_id,
    "id": RolePermission.id,
}
USER_ROLE_SORT_COLUMNS = {
    "user_id": UserRole.user_id,
    "role_id": UserRole.role_id,
    "id": UserRole.id,
}


async def user_has_permission(db: AsyncSession, user: User, permission_code: str) -> bool:
    stmt = (
        select(Permission.id)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .join(Role, Role.id == UserRole.role_id)
        .where(
            UserRole.tenant_id == user.tenant_id,
            UserRole.user_id == user.id,
            RolePermission.tenant_id == user.tenant_id,
            Permission.code == permission_code,
            Role.is_active.is_(True),
        )
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.first() is not None


async def list_permissions(db: AsyncSession) -> list[Permission]:
    result = await db.execute(
        select(Permission).order_by(Permission.module.asc(), Permission.code.asc())
    )
    return list(result.scalars().all())


async def list_role_permissions(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: RolePermissionFilters,
    sort: tuple[SortSpec, ...],
) -> Page[RolePermission]:
    stmt = _apply_role_permission_filters(
        select(RolePermission).where(RolePermission.tenant_id == tenant_id),
        filters,
    )
    stmt = apply_sort(stmt, sort, ROLE_PERMISSION_SORT_COLUMNS)
    count_stmt = _apply_role_permission_filters(
        select(func.count(RolePermission.id)).where(RolePermission.tenant_id == tenant_id),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def get_role_permission_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    role_permission_id: uuid.UUID,
) -> RolePermission | None:
    return await db.scalar(
        select(RolePermission).where(
            RolePermission.tenant_id == tenant_id,
            RolePermission.id == role_permission_id,
        )
    )


async def create_role_permission(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: RolePermissionCreate,
    *,
    actor_user_id: uuid.UUID,
) -> RolePermission:
    await _ensure_active_role(db, tenant_id, data.role_id)
    await _ensure_permission(db, data.permission_id)
    await _ensure_role_permission_available(db, tenant_id, data.role_id, data.permission_id)
    link = RolePermission(tenant_id=tenant_id, **data.model_dump())
    db.add(link)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="roles.assign_permission",
        entity_type="role_permission",
        entity_id=link.id,
        after_json=_loggable_role_permission(link),
    )
    await db.commit()
    await db.refresh(link)
    return link


async def delete_role_permission(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    role_permission_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    link = await get_role_permission_by_id(db, tenant_id, role_permission_id)
    if link is None:
        raise RolePermissionNotFound()
    before = _loggable_role_permission(link)
    await db.delete(link)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="roles.revoke_permission",
        entity_type="role_permission",
        entity_id=link.id,
        before_json=before,
    )
    await db.commit()


async def list_user_roles(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: UserRoleFilters,
    sort: tuple[SortSpec, ...],
) -> Page[UserRole]:
    stmt = _apply_user_role_filters(
        select(UserRole).where(UserRole.tenant_id == tenant_id),
        filters,
    )
    stmt = apply_sort(stmt, sort, USER_ROLE_SORT_COLUMNS)
    count_stmt = _apply_user_role_filters(
        select(func.count(UserRole.id)).where(UserRole.tenant_id == tenant_id),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def get_user_role_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_role_id: uuid.UUID,
) -> UserRole | None:
    return await db.scalar(
        select(UserRole).where(UserRole.tenant_id == tenant_id, UserRole.id == user_role_id)
    )


async def create_user_role(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: UserRoleCreate,
    *,
    actor_user_id: uuid.UUID,
) -> UserRole:
    await _ensure_active_user(db, tenant_id, data.user_id)
    await _ensure_active_role(db, tenant_id, data.role_id)
    await _ensure_user_role_available(db, tenant_id, data.user_id, data.role_id)
    link = UserRole(tenant_id=tenant_id, **data.model_dump())
    db.add(link)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="users.assign_role",
        entity_type="user_role",
        entity_id=link.id,
        after_json=_loggable_user_role(link),
    )
    await db.commit()
    await db.refresh(link)
    return link


async def delete_user_role(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_role_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    link = await get_user_role_by_id(db, tenant_id, user_role_id)
    if link is None:
        raise UserRoleNotFound()
    before = _loggable_user_role(link)
    await db.delete(link)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="users.revoke_role",
        entity_type="user_role",
        entity_id=link.id,
        before_json=before,
    )
    await db.commit()


async def list_roles(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: RoleFilters,
    sort: tuple[SortSpec, ...],
) -> Page[Role]:
    stmt = _apply_filters(select(Role).where(Role.tenant_id == tenant_id), filters).options(
        selectinload(Role.permission_links).joinedload(RolePermission.permission)
    )
    stmt = apply_sort(stmt, sort, ROLE_SORT_COLUMNS)
    count_stmt = _apply_filters(
        select(func.count(Role.id)).where(Role.tenant_id == tenant_id), filters
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def get_role_by_id(db: AsyncSession, tenant_id: uuid.UUID, role_id: uuid.UUID) -> Role | None:
    result = await db.execute(
        select(Role)
        .where(Role.tenant_id == tenant_id, Role.id == role_id)
        .options(selectinload(Role.permission_links).joinedload(RolePermission.permission))
    )
    return result.scalar_one_or_none()


async def create_role(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: RoleCreate,
    *,
    actor_user_id: uuid.UUID,
) -> Role:
    await _ensure_role_code_available(db, tenant_id, data.code)
    await _ensure_permissions(db, data.permission_ids)
    role = Role(
        tenant_id=tenant_id,
        code=data.code,
        name=data.name,
        description=data.description,
        is_active=data.is_active,
    )
    db.add(role)
    await db.flush()
    await _replace_permissions(db, role, data.permission_ids)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="roles.create",
        entity_type="role",
        entity_id=role.id,
        after_json=_loggable(role),
    )
    await db.commit()
    created = await get_role_by_id(db, tenant_id, role.id)
    if created is None:
        raise RoleNotFound()
    return created


async def update_role(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    role_id: uuid.UUID,
    data: RoleUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> Role:
    role = await get_role_by_id(db, tenant_id, role_id)
    if role is None:
        raise RoleNotFound()
    if role.is_system and data.is_active is False:
        raise ProtectedRole()
    before = _loggable(role)
    fields = data.model_dump(exclude_unset=True, exclude={"permission_ids"})
    if "code" in fields and fields["code"] != role.code:
        await _ensure_role_code_available(db, tenant_id, fields["code"], role_id=role.id)
    for key, value in fields.items():
        setattr(role, key, value)
    if data.permission_ids is not None:
        await _ensure_permissions(db, data.permission_ids)
        await _replace_permissions(db, role, data.permission_ids)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="roles.update",
        entity_type="role",
        entity_id=role.id,
        before_json=before,
        after_json=_loggable(role),
    )
    await db.commit()
    updated = await get_role_by_id(db, tenant_id, role.id)
    if updated is None:
        raise RoleNotFound()
    return updated


async def deactivate_role(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    role_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    role = await get_role_by_id(db, tenant_id, role_id)
    if role is None:
        raise RoleNotFound()
    if role.is_system:
        raise ProtectedRole()
    assigned = await db.scalar(
        select(func.count(UserRole.id)).where(
            UserRole.tenant_id == tenant_id, UserRole.role_id == role_id
        )
    )
    if assigned:
        raise RoleAssigned()
    await update_role(
        db,
        tenant_id,
        role_id,
        RoleUpdate(is_active=False),
        actor_user_id=actor_user_id,
    )


async def _ensure_role_code_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    code: str,
    *,
    role_id: uuid.UUID | None = None,
) -> None:
    existing = await db.scalar(select(Role).where(Role.tenant_id == tenant_id, Role.code == code))
    if existing is not None and existing.id != role_id:
        raise RoleCodeConflict()


async def _ensure_permissions(db: AsyncSession, permission_ids: list[uuid.UUID]) -> None:
    unique_permission_ids = set(permission_ids)
    if not unique_permission_ids:
        return
    found = await db.scalar(
        select(func.count(Permission.id)).where(Permission.id.in_(unique_permission_ids))
    )
    if found != len(unique_permission_ids):
        raise InvalidPermission()


async def _replace_permissions(
    db: AsyncSession, role: Role, permission_ids: list[uuid.UUID]
) -> None:
    await db.refresh(role, attribute_names=["permission_links"])
    role.permission_links = [
        RolePermission(tenant_id=role.tenant_id, role_id=role.id, permission_id=permission_id)
        for permission_id in set(permission_ids)
    ]


def _apply_filters[StmtT: Select[Any]](stmt: StmtT, filters: RoleFilters) -> StmtT:
    search = search_clause([Role.code, Role.name, Role.description], filters.search)
    if search is not None:
        stmt = stmt.where(search)
    if filters.is_active is not None:
        stmt = stmt.where(Role.is_active == filters.is_active)
    return stmt


def _apply_role_permission_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: RolePermissionFilters,
) -> StmtT:
    if filters.role_id is not None:
        stmt = stmt.where(RolePermission.role_id == filters.role_id)
    if filters.permission_id is not None:
        stmt = stmt.where(RolePermission.permission_id == filters.permission_id)
    return stmt


def _apply_user_role_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: UserRoleFilters,
) -> StmtT:
    if filters.user_id is not None:
        stmt = stmt.where(UserRole.user_id == filters.user_id)
    if filters.role_id is not None:
        stmt = stmt.where(UserRole.role_id == filters.role_id)
    return stmt


async def _ensure_active_role(db: AsyncSession, tenant_id: uuid.UUID, role_id: uuid.UUID) -> Role:
    role = await db.scalar(
        select(Role).where(
            Role.tenant_id == tenant_id,
            Role.id == role_id,
            Role.is_active.is_(True),
        )
    )
    if role is None:
        raise InvalidRole()
    return role


async def _ensure_active_user(db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID) -> User:
    user = await db.scalar(
        select(User).where(
            User.tenant_id == tenant_id,
            User.id == user_id,
            User.status == UserStatus.ACTIVE,
        )
    )
    if user is None:
        raise InvalidUser()
    return user


async def _ensure_permission(db: AsyncSession, permission_id: uuid.UUID) -> Permission:
    permission = await db.scalar(select(Permission).where(Permission.id == permission_id))
    if permission is None:
        raise InvalidPermission()
    return permission


async def _ensure_role_permission_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    role_id: uuid.UUID,
    permission_id: uuid.UUID,
) -> None:
    existing = await db.scalar(
        select(RolePermission).where(
            RolePermission.tenant_id == tenant_id,
            RolePermission.role_id == role_id,
            RolePermission.permission_id == permission_id,
        )
    )
    if existing is not None:
        raise RolePermissionConflict()


async def _ensure_user_role_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    role_id: uuid.UUID,
) -> None:
    existing = await db.scalar(
        select(UserRole).where(
            UserRole.tenant_id == tenant_id,
            UserRole.user_id == user_id,
            UserRole.role_id == role_id,
        )
    )
    if existing is not None:
        raise UserRoleConflict()


def _loggable(role: Role) -> dict[str, Any]:
    return {
        "code": role.code,
        "name": role.name,
        "is_system": role.is_system,
        "is_active": role.is_active,
        "permission_ids": [str(link.permission_id) for link in role.permission_links],
    }


def _loggable_role_permission(link: RolePermission) -> dict[str, Any]:
    return {
        "role_id": str(link.role_id),
        "permission_id": str(link.permission_id),
    }


def _loggable_user_role(link: UserRole) -> dict[str, Any]:
    return {
        "user_id": str(link.user_id),
        "role_id": str(link.role_id),
    }
