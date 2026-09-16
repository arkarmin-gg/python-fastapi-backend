import asyncio
import os
from datetime import UTC, datetime

import src.registry  # noqa: F401
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.database import SessionFactory
from src.foundation_enums import MembershipStatus, OrganizationStatus, UserStatus
from src.modules.auth import security
from src.modules.memberships.models import OrganizationMembership
from src.modules.organizations.models import Organization
from src.modules.rbac.constants import (
    FOUNDATION_PERMISSION_MODULES,
    MODULE_EXTRA_ACTIONS,
    OWNER_ROLE_CODE,
    OWNER_TEMPLATE_CODE,
    ActionType,
    extra_permission_code,
    permission_code,
)
from src.modules.rbac.models import (
    MembershipRole,
    Permission,
    Role,
    RolePermission,
    RoleTemplate,
    RoleTemplatePermission,
)
from src.modules.users.models import User
from src.modules.users.normalize import normalize_email, normalize_phone


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


async def _ensure_owner_template(db: AsyncSession, permissions: list[Permission]) -> RoleTemplate:
    template = await db.scalar(select(RoleTemplate).where(RoleTemplate.code == OWNER_TEMPLATE_CODE))
    if template is None:
        template = RoleTemplate(
            code=OWNER_TEMPLATE_CODE,
            name="Owner",
            description="Full organization administration access.",
            is_active=True,
        )
        db.add(template)
        await db.flush()
    existing = {
        pid
        for (pid,) in (
            await db.execute(
                select(RoleTemplatePermission.permission_id).where(
                    RoleTemplatePermission.role_template_id == template.id
                )
            )
        ).all()
    }
    for permission in permissions:
        if permission.id not in existing:
            db.add(
                RoleTemplatePermission(
                    role_template_id=template.id,
                    permission_id=permission.id,
                )
            )
    await db.flush()
    return template


async def _get_or_create_org(db: AsyncSession) -> Organization:
    code = os.environ.get("ORGANIZATION_CODE", os.environ.get("TENANT_CODE", "demo"))
    name = os.environ.get("ORGANIZATION_NAME", os.environ.get("TENANT_NAME", "Demo Organization"))
    org = await db.scalar(select(Organization).where(Organization.code == code))
    if org is None:
        org = Organization(
            code=code,
            name=name,
            status=OrganizationStatus.ACTIVE,
        )
        db.add(org)
        await db.flush()
    return org


async def _ensure_owner_role(
    db: AsyncSession,
    org: Organization,
    template: RoleTemplate,
    permissions: list[Permission],
) -> Role:
    role = await db.scalar(
        select(Role).where(Role.organization_id == org.id, Role.code == OWNER_ROLE_CODE)
    )
    if role is None:
        role = Role(
            organization_id=org.id,
            template_id=template.id,
            code=OWNER_ROLE_CODE,
            name="Owner",
            description="Full organization administration access.",
            is_system=True,
        )
        db.add(role)
        await db.flush()
    existing = {
        pid
        for (pid,) in (
            await db.execute(
                select(RolePermission.permission_id).where(
                    RolePermission.organization_id == org.id,
                    RolePermission.role_id == role.id,
                )
            )
        ).all()
    }
    for permission in permissions:
        if permission.id not in existing:
            db.add(
                RolePermission(
                    organization_id=org.id,
                    role_id=role.id,
                    permission_id=permission.id,
                )
            )
    await db.flush()
    return role


async def _get_or_create_owner(db: AsyncSession, org: Organization, role: Role) -> tuple[str, bool]:
    email = os.environ.get("USER_EMAIL", os.environ.get("ADMIN_EMAIL", "owner@example.com"))
    phone = os.environ.get("USER_PHONE")
    password = os.environ.get("USER_PASSWORD", os.environ.get("ADMIN_PASSWORD", "ChangeMe123!"))
    email_n = normalize_email(email)
    phone_n = normalize_phone(phone)
    user = None
    if email_n:
        user = await db.scalar(select(User).where(User.email_normalized == email_n))
    created = False
    if user is None:
        user = User(
            name=os.environ.get("USER_NAME", "Owner User"),
            email=email,
            email_normalized=email_n,
            phone=phone,
            phone_normalized=phone_n,
            password_hash=security.hash_password(password),
            status=UserStatus.ACTIVE,
        )
        db.add(user)
        await db.flush()
        created = True

    now = datetime.now(UTC)
    membership = await db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == org.id,
            OrganizationMembership.user_id == user.id,
        )
    )
    if membership is None:
        membership = OrganizationMembership(
            organization_id=org.id,
            user_id=user.id,
            status=MembershipStatus.ACTIVE,
            joined_at=now,
            activated_at=now,
        )
        db.add(membership)
        await db.flush()

    link = await db.scalar(
        select(MembershipRole).where(
            MembershipRole.organization_id == org.id,
            MembershipRole.membership_id == membership.id,
            MembershipRole.role_id == role.id,
        )
    )
    if link is None:
        db.add(
            MembershipRole(
                organization_id=org.id,
                membership_id=membership.id,
                role_id=role.id,
            )
        )
    return email, created


async def main() -> None:
    async with SessionFactory() as db:
        permissions = await _ensure_permissions(db)
        template = await _ensure_owner_template(db, permissions)
        org = await _get_or_create_org(db)
        role = await _ensure_owner_role(db, org, template, permissions)
        email, created = await _get_or_create_owner(db, org, role)
        await db.commit()
        print(f"Organization: {org.code} ({org.id})")
        print(f"Owner user: {email} ({'created' if created else 'exists'})")


if __name__ == "__main__":
    asyncio.run(main())
