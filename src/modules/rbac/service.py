import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.modules.audit_logs.service import record_audit_log
from src.modules.rbac.exceptions import (
    InvalidPermission,
    InvalidRole,
    InvalidUser,
    MembershipRoleConflict,
    MembershipRoleNotFound,
    ProtectedRole,
    RoleAssigned,
    RoleCodeConflict,
    RoleNotFound,
    RolePermissionConflict,
    RolePermissionNotFound,
)
from src.modules.rbac.models import MembershipRole, Permission, Role, RolePermission
from src.modules.rbac.schemas import (
    MembershipRoleCreate,
    MembershipRoleFilters,
    RoleCreate,
    RoleFilters,
    RolePermissionCreate,
    RolePermissionFilters,
    RoleUpdate,
)
from src.modules.users.models import User
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
    "membership_id": MembershipRole.membership_id,
    "role_id": MembershipRole.role_id,
    "id": MembershipRole.id,
}


async def user_has_permission(
    db: AsyncSession,
    user: User,
    permission_code: str,
    *,
    organization_id: uuid.UUID,
    membership_id: uuid.UUID,
) -> bool:
    from src.modules.memberships.models import OrganizationMembership

    result = await db.scalar(
        select(Permission.id)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, Role.id == RolePermission.role_id)
        .join(MembershipRole, MembershipRole.role_id == Role.id)
        .join(OrganizationMembership, OrganizationMembership.id == MembershipRole.membership_id)
        .where(
            OrganizationMembership.id == membership_id,
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user.id,
            RolePermission.organization_id == organization_id,
            MembershipRole.organization_id == organization_id,
            Permission.code == permission_code,
            Permission.is_active.is_(True),
            Role.is_active.is_(True),
            Role.organization_id == organization_id,
            or_(
                MembershipRole.expires_at.is_(None),
                MembershipRole.expires_at > datetime.now(UTC),
            ),
        )
        .limit(1)
    )
    return result is not None


async def list_permissions(db: AsyncSession) -> list[Permission]:
    result = await db.execute(
        select(Permission).order_by(Permission.module.asc(), Permission.code.asc())
    )
    return list(result.scalars().all())


async def list_role_permissions(
    db: AsyncSession,
    organization_id: uuid.UUID,
    pagination: PaginationParams,
    filters: RolePermissionFilters,
    sort: tuple[SortSpec, ...],
) -> Page[RolePermission]:
    stmt = _apply_role_permission_filters(
        select(RolePermission).where(RolePermission.organization_id == organization_id),
        filters,
    )
    stmt = apply_sort(stmt, sort, ROLE_PERMISSION_SORT_COLUMNS)
    count_stmt = _apply_role_permission_filters(
        select(func.count(RolePermission.id)).where(
            RolePermission.organization_id == organization_id
        ),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def get_role_permission_by_id(
    db: AsyncSession,
    organization_id: uuid.UUID,
    role_permission_id: uuid.UUID,
) -> RolePermission | None:
    return await db.scalar(
        select(RolePermission).where(
            RolePermission.organization_id == organization_id,
            RolePermission.id == role_permission_id,
        )
    )


async def create_role_permission(
    db: AsyncSession,
    organization_id: uuid.UUID,
    data: RolePermissionCreate,
    *,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID | None = None,
) -> RolePermission:
    await _ensure_active_role(db, organization_id, data.role_id)
    await _ensure_permission(db, data.permission_id)
    await _ensure_role_permission_available(db, organization_id, data.role_id, data.permission_id)
    link = RolePermission(
        organization_id=organization_id,
        granted_by_membership_id=actor_membership_id,
        **data.model_dump(),
    )
    db.add(link)
    await db.flush()
    await record_audit_log(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        actor_membership_id=actor_membership_id,
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
    organization_id: uuid.UUID,
    role_permission_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID | None = None,
) -> None:
    link = await get_role_permission_by_id(db, organization_id, role_permission_id)
    if link is None:
        raise RolePermissionNotFound()
    before = _loggable_role_permission(link)
    await db.delete(link)
    await db.flush()
    await record_audit_log(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        actor_membership_id=actor_membership_id,
        action="roles.revoke_permission",
        entity_type="role_permission",
        entity_id=link.id,
        before_json=before,
    )
    await db.commit()


async def list_membership_roles(
    db: AsyncSession,
    organization_id: uuid.UUID,
    pagination: PaginationParams,
    filters: MembershipRoleFilters,
    sort: tuple[SortSpec, ...],
) -> Page[MembershipRole]:
    stmt = _apply_membership_role_filters(
        select(MembershipRole).where(MembershipRole.organization_id == organization_id),
        filters,
    )
    stmt = apply_sort(stmt, sort, USER_ROLE_SORT_COLUMNS)
    count_stmt = _apply_membership_role_filters(
        select(func.count(MembershipRole.id)).where(
            MembershipRole.organization_id == organization_id
        ),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def get_membership_role_by_id(
    db: AsyncSession,
    organization_id: uuid.UUID,
    membership_role_id: uuid.UUID,
) -> MembershipRole | None:
    return await db.scalar(
        select(MembershipRole).where(
            MembershipRole.organization_id == organization_id,
            MembershipRole.id == membership_role_id,
        )
    )


async def create_membership_role(
    db: AsyncSession,
    organization_id: uuid.UUID,
    data: MembershipRoleCreate,
    *,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID | None = None,
) -> MembershipRole:
    await _ensure_active_membership(db, organization_id, data.membership_id)
    await _ensure_active_role(db, organization_id, data.role_id)
    await _ensure_membership_role_available(db, organization_id, data.membership_id, data.role_id)
    link = MembershipRole(
        organization_id=organization_id,
        assigned_by_membership_id=actor_membership_id,
        **data.model_dump(),
    )
    db.add(link)
    await db.flush()
    await record_audit_log(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        actor_membership_id=actor_membership_id,
        action="users.assign_role",
        entity_type="membership_role",
        entity_id=link.id,
        after_json=_loggable_membership_role(link),
    )
    await db.commit()
    await db.refresh(link)
    return link


async def delete_membership_role(
    db: AsyncSession,
    organization_id: uuid.UUID,
    membership_role_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID | None = None,
) -> None:
    link = await get_membership_role_by_id(db, organization_id, membership_role_id)
    if link is None:
        raise MembershipRoleNotFound()
    before = _loggable_membership_role(link)
    await db.delete(link)
    await db.flush()
    await record_audit_log(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        actor_membership_id=actor_membership_id,
        action="users.revoke_role",
        entity_type="membership_role",
        entity_id=link.id,
        before_json=before,
    )
    await db.commit()


async def list_roles(
    db: AsyncSession,
    organization_id: uuid.UUID,
    pagination: PaginationParams,
    filters: RoleFilters,
    sort: tuple[SortSpec, ...],
) -> Page[Role]:
    stmt = _apply_filters(
        select(Role).where(Role.organization_id == organization_id), filters
    ).options(selectinload(Role.permission_links).joinedload(RolePermission.permission))
    stmt = apply_sort(stmt, sort, ROLE_SORT_COLUMNS)
    count_stmt = _apply_filters(
        select(func.count(Role.id)).where(Role.organization_id == organization_id), filters
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def get_role_by_id(
    db: AsyncSession, organization_id: uuid.UUID, role_id: uuid.UUID
) -> Role | None:
    result = await db.execute(
        select(Role)
        .where(Role.organization_id == organization_id, Role.id == role_id)
        .options(selectinload(Role.permission_links).joinedload(RolePermission.permission))
    )
    return result.scalar_one_or_none()


async def create_role(
    db: AsyncSession,
    organization_id: uuid.UUID,
    data: RoleCreate,
    *,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID | None = None,
) -> Role:
    await _ensure_role_code_available(db, organization_id, data.code)
    await _ensure_permissions(db, data.permission_ids)
    role = Role(
        organization_id=organization_id,
        code=data.code,
        name=data.name,
        description=data.description,
        is_active=data.is_active,
    )
    db.add(role)
    await db.flush()
    await _replace_permissions(
        db,
        role,
        data.permission_ids,
        actor_membership_id=actor_membership_id,
    )
    await db.flush()
    await record_audit_log(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        actor_membership_id=actor_membership_id,
        action="roles.create",
        entity_type="role",
        entity_id=role.id,
        after_json=_loggable(role),
    )
    await db.commit()
    created = await get_role_by_id(db, organization_id, role.id)
    if created is None:
        raise RoleNotFound()
    return created


async def update_role(
    db: AsyncSession,
    organization_id: uuid.UUID,
    role_id: uuid.UUID,
    data: RoleUpdate,
    *,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID | None = None,
) -> Role:
    role = await get_role_by_id(db, organization_id, role_id)
    if role is None:
        raise RoleNotFound()
    if role.is_system and data.is_active is False:
        raise ProtectedRole()
    before = _loggable(role)
    fields = data.model_dump(exclude_unset=True, exclude={"permission_ids"})
    if "code" in fields and fields["code"] != role.code:
        await _ensure_role_code_available(db, organization_id, fields["code"], role_id=role.id)
    for key, value in fields.items():
        setattr(role, key, value)
    if data.permission_ids is not None:
        await _ensure_permissions(db, data.permission_ids)
        await _replace_permissions(
            db,
            role,
            data.permission_ids,
            actor_membership_id=actor_membership_id,
        )
    await db.flush()
    await record_audit_log(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        actor_membership_id=actor_membership_id,
        action="roles.update",
        entity_type="role",
        entity_id=role.id,
        before_json=before,
        after_json=_loggable(role),
    )
    await db.commit()
    updated = await get_role_by_id(db, organization_id, role.id)
    if updated is None:
        raise RoleNotFound()
    return updated


async def deactivate_role(
    db: AsyncSession,
    organization_id: uuid.UUID,
    role_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID | None = None,
) -> None:
    role = await get_role_by_id(db, organization_id, role_id)
    if role is None:
        raise RoleNotFound()
    if role.is_system:
        raise ProtectedRole()
    assigned = await db.scalar(
        select(func.count(MembershipRole.id)).where(
            MembershipRole.organization_id == organization_id, MembershipRole.role_id == role_id
        )
    )
    if assigned:
        raise RoleAssigned()
    await update_role(
        db,
        organization_id,
        role_id,
        RoleUpdate(is_active=False),
        actor_user_id=actor_user_id,
        actor_membership_id=actor_membership_id,
    )


async def _ensure_role_code_available(
    db: AsyncSession,
    organization_id: uuid.UUID,
    code: str,
    *,
    role_id: uuid.UUID | None = None,
) -> None:
    existing = await db.scalar(
        select(Role).where(Role.organization_id == organization_id, Role.code == code)
    )
    if existing is not None and existing.id != role_id:
        raise RoleCodeConflict()


async def _ensure_permissions(db: AsyncSession, permission_ids: list[uuid.UUID]) -> None:
    unique_permission_ids = set(permission_ids)
    if not unique_permission_ids:
        return
    found = await db.scalar(
        select(func.count(Permission.id)).where(
            Permission.id.in_(unique_permission_ids),
            Permission.is_active.is_(True),
        )
    )
    if found != len(unique_permission_ids):
        raise InvalidPermission()


async def _replace_permissions(
    db: AsyncSession,
    role: Role,
    permission_ids: list[uuid.UUID],
    *,
    actor_membership_id: uuid.UUID | None,
) -> None:
    await db.refresh(role, attribute_names=["permission_links"])
    role.permission_links = [
        RolePermission(
            organization_id=role.organization_id,
            role_id=role.id,
            permission_id=permission_id,
            granted_by_membership_id=actor_membership_id,
        )
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


def _apply_membership_role_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: MembershipRoleFilters,
) -> StmtT:
    if filters.membership_id is not None:
        stmt = stmt.where(MembershipRole.membership_id == filters.membership_id)
    if filters.role_id is not None:
        stmt = stmt.where(MembershipRole.role_id == filters.role_id)
    return stmt


async def _ensure_active_role(
    db: AsyncSession, organization_id: uuid.UUID, role_id: uuid.UUID
) -> Role:
    role = await db.scalar(
        select(Role).where(
            Role.organization_id == organization_id,
            Role.id == role_id,
            Role.is_active.is_(True),
        )
    )
    if role is None:
        raise InvalidRole()
    return role


async def _ensure_active_membership(
    db: AsyncSession, organization_id: uuid.UUID, membership_id: uuid.UUID
):
    from src.foundation_enums import MembershipStatus
    from src.modules.memberships.models import OrganizationMembership

    membership = await db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.id == membership_id,
            OrganizationMembership.status == MembershipStatus.ACTIVE,
        )
    )
    if membership is None:
        raise InvalidUser()
    return membership


async def _ensure_permission(db: AsyncSession, permission_id: uuid.UUID) -> Permission:
    permission = await db.scalar(
        select(Permission).where(
            Permission.id == permission_id,
            Permission.is_active.is_(True),
        )
    )
    if permission is None:
        raise InvalidPermission()
    return permission


async def _ensure_role_permission_available(
    db: AsyncSession,
    organization_id: uuid.UUID,
    role_id: uuid.UUID,
    permission_id: uuid.UUID,
) -> None:
    existing = await db.scalar(
        select(RolePermission).where(
            RolePermission.organization_id == organization_id,
            RolePermission.role_id == role_id,
            RolePermission.permission_id == permission_id,
        )
    )
    if existing is not None:
        raise RolePermissionConflict()


async def _ensure_membership_role_available(
    db: AsyncSession,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    role_id: uuid.UUID,
) -> None:
    existing = await db.scalar(
        select(MembershipRole).where(
            MembershipRole.organization_id == organization_id,
            MembershipRole.membership_id == user_id,
            MembershipRole.role_id == role_id,
        )
    )
    if existing is not None:
        raise MembershipRoleConflict()


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


def _loggable_membership_role(link: MembershipRole) -> dict[str, Any]:
    return {
        "membership_id": str(link.membership_id),
        "role_id": str(link.role_id),
    }
