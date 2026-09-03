import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.foundation_enums import UserStatus
from src.modules.audit_logs.models import AuditLog
from src.modules.rbac.constants import ActionType
from src.modules.rbac.models import Permission, Role, RolePermission
from src.modules.users.models import UserRole

from tests.conftest import (
    auth_headers,
    make_tenant,
    make_user_with_permissions,
    permission,
    user_access_token,
)


async def test_users_crud_is_tenant_scoped_and_audited(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="crud")
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[
            permission("users", ActionType.CREATE),
            permission("users", ActionType.READ),
            permission("users", ActionType.UPDATE),
            permission("users", ActionType.DELETE),
            permission("audit_logs", ActionType.READ),
        ],
    )
    headers = auth_headers(user_access_token(actor))

    create_response = await client.post(
        "/api/v1/users",
        json={
            "name": "Cashier",
            "email": "cashier@example.com",
            "password": "Password123!",
            "role_ids": [],
        },
        headers=headers,
    )

    assert create_response.status_code == 201
    user_id = create_response.json()["id"]

    list_response = await client.get("/api/v1/users", headers=headers)
    assert list_response.status_code == 200
    assert user_id in [item["id"] for item in list_response.json()["items"]]

    update_response = await client.patch(
        f"/api/v1/users/{user_id}",
        json={"status": UserStatus.INACTIVE.value},
        headers=headers,
    )
    assert update_response.status_code == 200
    assert update_response.json()["status"] == UserStatus.INACTIVE.value

    logs = await client.get("/api/v1/audit-logs", headers=headers)
    assert logs.status_code == 200
    assert {item["action"] for item in logs.json()["items"]} >= {"users.create", "users.update"}


async def test_role_crud_and_permission_catalog(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="roles")
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[
            permission("roles", ActionType.CREATE),
            permission("roles", ActionType.READ),
            permission("roles", ActionType.UPDATE),
            permission("permissions", ActionType.READ),
        ],
    )
    target_permission = Permission(code="catalog.read", name="Catalog Read", module="catalog")
    db_session.add(target_permission)
    await db_session.flush()
    headers = auth_headers(user_access_token(actor))

    permissions_response = await client.get("/api/v1/permissions", headers=headers)
    assert permissions_response.status_code == 200

    create_response = await client.post(
        "/api/v1/roles",
        json={
            "code": "manager",
            "name": "Manager",
            "permission_ids": [str(target_permission.id)],
        },
        headers=headers,
    )
    assert create_response.status_code == 201
    assert create_response.json()["permissions"][0]["code"] == "catalog.read"

    update_response = await client.patch(
        f"/api/v1/roles/{create_response.json()['id']}",
        json={"name": "Store Manager"},
        headers=headers,
    )
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "Store Manager"


async def test_rbac_assignment_lifecycle_is_tenant_scoped_and_audited(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="rbac-assignments")
    other_tenant = await make_tenant(db_session, code="rbac-assignments-other")
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[
            permission("roles", ActionType.CREATE),
            permission("roles", ActionType.READ),
            permission("roles", ActionType.UPDATE),
            permission("users", ActionType.CREATE),
            permission("users", ActionType.READ),
            permission("users", ActionType.UPDATE),
        ],
    )
    read_only = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[
            permission("roles", ActionType.READ),
            permission("users", ActionType.READ),
        ],
    )
    target_permission = Permission(code="catalog.read", name="Catalog Read", module="catalog")
    db_session.add(target_permission)
    other_role = Role(tenant_id=other_tenant.id, code="other-role", name="Other Role")
    db_session.add(other_role)
    await db_session.flush()
    other_role_permission = RolePermission(
        tenant_id=other_tenant.id,
        role_id=other_role.id,
        permission_id=target_permission.id,
    )
    db_session.add(other_role_permission)
    await db_session.flush()
    headers = auth_headers(user_access_token(actor))

    created_role = await client.post(
        "/api/v1/roles",
        json={"code": "cashier", "name": "Cashier", "permission_ids": []},
        headers=headers,
    )
    created_user = await client.post(
        "/api/v1/users",
        json={
            "name": "Assignable User",
            "email": "assignable@example.com",
            "password": "Password123!",
            "role_ids": [],
        },
        headers=headers,
    )
    assert created_role.status_code == 201
    assert created_user.status_code == 201
    role_id = created_role.json()["id"]
    user_id = created_user.json()["id"]

    denied_role_permission = await client.post(
        "/api/v1/role-permissions",
        json={"role_id": role_id, "permission_id": str(target_permission.id)},
        headers=auth_headers(user_access_token(read_only)),
    )
    role_permission = await client.post(
        "/api/v1/role-permissions",
        json={"role_id": role_id, "permission_id": str(target_permission.id)},
        headers=headers,
    )
    role_permission_id = role_permission.json()["id"]
    duplicate_role_permission = await client.post(
        "/api/v1/role-permissions",
        json={"role_id": role_id, "permission_id": str(target_permission.id)},
        headers=headers,
    )
    invalid_role_permission = await client.post(
        "/api/v1/role-permissions",
        json={"role_id": str(other_role.id), "permission_id": str(target_permission.id)},
        headers=headers,
    )
    listed_role_permissions = await client.get(
        f"/api/v1/role-permissions?role_id={role_id}",
        headers=headers,
    )
    fetched_role_permission = await client.get(
        f"/api/v1/role-permissions/{role_permission_id}",
        headers=headers,
    )
    hidden_role_permission = await client.get(
        f"/api/v1/role-permissions/{other_role_permission.id}",
        headers=headers,
    )

    assert denied_role_permission.status_code == 403
    assert role_permission.status_code == 201
    assert role_permission.json()["role_id"] == role_id
    assert duplicate_role_permission.status_code == 409
    assert duplicate_role_permission.json()["error_code"] == "role_permission_conflict"
    assert invalid_role_permission.status_code == 400
    assert invalid_role_permission.json()["error_code"] == "invalid_role"
    assert listed_role_permissions.status_code == 200
    assert [row["id"] for row in listed_role_permissions.json()["items"]] == [role_permission_id]
    assert fetched_role_permission.status_code == 200
    assert fetched_role_permission.json()["permission_id"] == str(target_permission.id)
    assert hidden_role_permission.status_code == 404

    user_role = await client.post(
        "/api/v1/user-roles",
        json={"user_id": user_id, "role_id": role_id},
        headers=headers,
    )
    user_role_id = user_role.json()["id"]
    duplicate_user_role = await client.post(
        "/api/v1/user-roles",
        json={"user_id": user_id, "role_id": role_id},
        headers=headers,
    )
    invalid_user_role = await client.post(
        "/api/v1/user-roles",
        json={"user_id": str(actor.id), "role_id": str(other_role.id)},
        headers=headers,
    )
    listed_user_roles = await client.get(f"/api/v1/user-roles?user_id={user_id}", headers=headers)
    fetched_user_role = await client.get(f"/api/v1/user-roles/{user_role_id}", headers=headers)

    assert user_role.status_code == 201
    assert user_role.json()["user_id"] == user_id
    assert duplicate_user_role.status_code == 409
    assert duplicate_user_role.json()["error_code"] == "user_role_conflict"
    assert invalid_user_role.status_code == 400
    assert invalid_user_role.json()["error_code"] == "invalid_role"
    assert listed_user_roles.status_code == 200
    assert [row["id"] for row in listed_user_roles.json()["items"]] == [user_role_id]
    assert fetched_user_role.status_code == 200
    assert fetched_user_role.json()["role_id"] == role_id

    deleted_user_role = await client.delete(f"/api/v1/user-roles/{user_role_id}", headers=headers)
    deleted_role_permission = await client.delete(
        f"/api/v1/role-permissions/{role_permission_id}",
        headers=headers,
    )

    assert deleted_user_role.status_code == 204
    assert deleted_role_permission.status_code == 204
    assert await db_session.get(UserRole, uuid.UUID(user_role_id)) is None
    assert await db_session.get(RolePermission, uuid.UUID(role_permission_id)) is None

    actions = {
        action
        for (action,) in (
            await db_session.execute(select(AuditLog.action).where(AuditLog.tenant_id == tenant.id))
        ).all()
    }
    assert {
        "roles.assign_permission",
        "roles.revoke_permission",
        "users.assign_role",
        "users.revoke_role",
    }.issubset(actions)


async def test_employee_crud(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="employees")
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[
            permission("employees", ActionType.CREATE),
            permission("employees", ActionType.READ),
            permission("employees", ActionType.UPDATE),
            permission("employees", ActionType.DELETE),
        ],
    )
    headers = auth_headers(user_access_token(actor))

    created = await client.post(
        "/api/v1/employees",
        json={"name": "Aye Aye"},
        headers=headers,
    )
    assert created.status_code == 201
    assert created.json()["code"].startswith("EMP-")

    updated = await client.patch(
        f"/api/v1/employees/{created.json()['id']}",
        json={"position": "Cashier"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["position"] == "Cashier"

    deleted = await client.delete(f"/api/v1/employees/{created.json()['id']}", headers=headers)
    assert deleted.status_code == 204


async def test_permission_denied_without_required_permission(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="denied")
    actor = await make_user_with_permissions(db_session, tenant=tenant, permissions=[])

    response = await client.get("/api/v1/users", headers=auth_headers(user_access_token(actor)))

    assert response.status_code == 403
    assert response.json()["error_code"] == "permission_denied"


async def test_audit_logs_are_tenant_scoped(db_session: AsyncSession) -> None:
    tenant_a = await make_tenant(db_session, code="tenant-a")
    tenant_b = await make_tenant(db_session, code="tenant-b")
    db_session.add(
        AuditLog(
            tenant_id=tenant_a.id,
            action="users.create",
            entity_type="user",
            entity_id=tenant_a.id,
        )
    )
    db_session.add(
        AuditLog(
            tenant_id=tenant_b.id,
            action="users.create",
            entity_type="user",
            entity_id=tenant_b.id,
        )
    )
    await db_session.flush()

    rows = (
        (await db_session.execute(select(AuditLog).where(AuditLog.tenant_id == tenant_a.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].entity_id == tenant_a.id
