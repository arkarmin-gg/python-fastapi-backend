import asyncio
import os

import src.registry  # noqa: F401
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.database import SessionFactory
from src.modules.auth import security
from src.modules.price_levels.constants import DEFAULT_PRICE_LEVELS
from src.modules.price_levels.models import PriceLevel
from src.modules.rbac.constants import (
    FOUNDATION_PERMISSION_MODULES,
    MODULE_EXTRA_ACTIONS,
    OWNER_ROLE_CODE,
    ActionType,
    extra_permission_code,
    permission_code,
)
from src.modules.rbac.models import Permission, Role, RolePermission
from src.modules.tenants.models import Tenant
from src.modules.units.constants import DEFAULT_UNITS
from src.modules.units.models import Unit
from src.modules.users.models import User, UserRole


async def _get_or_create_tenant(db: AsyncSession) -> Tenant:
    code = os.environ.get("TENANT_CODE", "demo")
    name = os.environ.get("TENANT_NAME", "Demo Grocery")
    tenant = await db.scalar(select(Tenant).where(Tenant.code == code))
    if tenant is None:
        tenant = Tenant(code=code, name=name)
        db.add(tenant)
        await db.flush()
    return tenant


async def _ensure_permissions(db: AsyncSession) -> list[Permission]:
    permissions: list[Permission] = []
    for module in FOUNDATION_PERMISSION_MODULES:
        for action in ActionType:
            code = permission_code(module, action)
            permission = await db.scalar(select(Permission).where(Permission.code == code))
            if permission is None:
                permission = Permission(
                    code=code,
                    name=f"{module.replace('_', ' ').title()} {action.value.title()}",
                    module=module,
                    description=f"Allows {action.value} access for {module}.",
                )
                db.add(permission)
                await db.flush()
            permissions.append(permission)
        for extra_action in MODULE_EXTRA_ACTIONS.get(module, ()):
            code = extra_permission_code(module, extra_action)
            permission = await db.scalar(select(Permission).where(Permission.code == code))
            if permission is None:
                permission = Permission(
                    code=code,
                    name=f"{module.replace('_', ' ').title()} {extra_action.title()}",
                    module=module,
                    description=f"Allows {extra_action} access for {module}.",
                )
                db.add(permission)
                await db.flush()
            permissions.append(permission)
    return permissions


async def _ensure_default_units(db: AsyncSession) -> list[Unit]:
    units: list[Unit] = []
    for unit_data in DEFAULT_UNITS:
        unit = await db.scalar(select(Unit).where(Unit.code == unit_data["code"]))
        if unit is None:
            unit = Unit(**unit_data)
            db.add(unit)
            await db.flush()
        units.append(unit)
    return units


async def _ensure_default_price_levels(db: AsyncSession, tenant: Tenant) -> list[PriceLevel]:
    price_levels: list[PriceLevel] = []
    for price_level_data in DEFAULT_PRICE_LEVELS:
        price_level = await db.scalar(
            select(PriceLevel).where(
                PriceLevel.tenant_id == tenant.id,
                PriceLevel.code == price_level_data["code"],
            )
        )
        if price_level is None:
            price_level = PriceLevel(tenant_id=tenant.id, **price_level_data)
            db.add(price_level)
            await db.flush()
        price_levels.append(price_level)
    return price_levels


async def _get_or_create_owner_role(
    db: AsyncSession,
    tenant: Tenant,
    permissions: list[Permission],
) -> Role:
    role = await db.scalar(
        select(Role).where(Role.tenant_id == tenant.id, Role.code == OWNER_ROLE_CODE)
    )
    if role is None:
        role = Role(
            tenant_id=tenant.id,
            code=OWNER_ROLE_CODE,
            name="Owner",
            description="Full tenant administration access.",
            is_system=True,
        )
        db.add(role)
        await db.flush()

    existing_ids = {
        permission_id
        for (permission_id,) in (
            await db.execute(
                select(RolePermission.permission_id).where(
                    RolePermission.tenant_id == tenant.id,
                    RolePermission.role_id == role.id,
                )
            )
        ).all()
    }
    for permission in permissions:
        if permission.id not in existing_ids:
            db.add(
                RolePermission(
                    tenant_id=tenant.id,
                    role_id=role.id,
                    permission_id=permission.id,
                )
            )
    return role


async def _get_or_create_owner_user(
    db: AsyncSession, tenant: Tenant, role: Role
) -> tuple[str, bool]:
    email = os.environ.get("USER_EMAIL", os.environ.get("ADMIN_EMAIL", "owner@example.com"))
    phone = os.environ.get("USER_PHONE")
    password = os.environ.get("USER_PASSWORD", os.environ.get("ADMIN_PASSWORD", "ChangeMe123!"))
    user = await db.scalar(select(User).where(User.tenant_id == tenant.id, User.email == email))
    created = False
    if user is None:
        user = User(
            tenant_id=tenant.id,
            name=os.environ.get("USER_NAME", "Owner User"),
            email=email,
            phone=phone,
            password_hash=security.hash_password(password),
        )
        db.add(user)
        await db.flush()
        created = True

    existing_role = await db.scalar(
        select(UserRole).where(
            UserRole.tenant_id == tenant.id,
            UserRole.user_id == user.id,
            UserRole.role_id == role.id,
        )
    )
    if existing_role is None:
        db.add(UserRole(tenant_id=tenant.id, user_id=user.id, role_id=role.id))
    return email, created


async def seed() -> None:
    async with SessionFactory() as db:
        tenant = await _get_or_create_tenant(db)
        permissions = await _ensure_permissions(db)
        # units = await _ensure_default_units(db)
        # price_levels = await _ensure_default_price_levels(db, tenant)
        role = await _get_or_create_owner_role(db, tenant, permissions)
        email, created = await _get_or_create_owner_user(db, tenant, role)
        await db.commit()

    print(
        f"Seed complete: tenant {tenant.code!r}, {len(permissions)} permissions, "
        f"owner user <{email}> {'created' if created else 'already existed'}."
    )
    # print(
    #     f"Seed complete: tenant {tenant.code!r}, {len(permissions)} permissions, "
    #     f"{len(units)} units, {len(price_levels)} price levels, "
    #     f"owner user <{email}> {'created' if created else 'already existed'}."
    # )


if __name__ == "__main__":
    asyncio.run(seed())
