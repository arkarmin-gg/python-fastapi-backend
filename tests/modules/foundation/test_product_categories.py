from httpx import AsyncClient
from scripts.seed import _ensure_permissions
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.modules.audit_logs.models import AuditLog
from src.modules.product_categories.models import ProductCategory
from src.modules.rbac.constants import ActionType
from src.modules.rbac.models import Permission

from tests.conftest import (
    auth_headers,
    make_tenant,
    make_user_with_permissions,
    permission,
    user_access_token,
)


async def test_product_category_crud_is_tenant_scoped_and_audited(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="categories-crud")
    other_tenant = await make_tenant(db_session, code="categories-other")
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[
            permission("product_categories", ActionType.CREATE),
            permission("product_categories", ActionType.READ),
            permission("product_categories", ActionType.UPDATE),
            permission("product_categories", ActionType.DELETE),
        ],
    )
    other_category = ProductCategory(
        tenant_id=other_tenant.id,
        code="grocery",
        name="Other Grocery",
    )
    db_session.add(other_category)
    await db_session.flush()
    headers = auth_headers(user_access_token(actor))

    created = await client.post(
        "/api/v1/product-categories",
        json={
            "name": "Grocery",
            "description": "General grocery items.",
        },
        headers=headers,
    )
    assert created.status_code == 201
    category_id = created.json()["id"]
    assert created.json()["code"].startswith("CAT-")

    listed = await client.get("/api/v1/product-categories?search=gro&sort=name", headers=headers)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [category_id]

    fetched = await client.get(f"/api/v1/product-categories/{category_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["tenant_id"] == str(tenant.id)

    not_found = await client.get(
        f"/api/v1/product-categories/{other_category.id}",
        headers=headers,
    )
    assert not_found.status_code == 404

    updated = await client.patch(
        f"/api/v1/product-categories/{category_id}",
        json={"name": "Groceries", "is_active": True},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Groceries"

    deleted = await client.delete(f"/api/v1/product-categories/{category_id}", headers=headers)
    assert deleted.status_code == 204

    category = await db_session.scalar(
        select(ProductCategory).where(ProductCategory.id == category_id)
    )
    assert category is not None
    assert category.is_active is False

    actions = (
        (
            await db_session.execute(
                select(AuditLog.action).where(
                    AuditLog.tenant_id == tenant.id,
                    AuditLog.entity_id == category.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert actions == [
        "product_categories.create",
        "product_categories.update",
        "product_categories.deactivate",
    ]


async def test_product_category_parent_filter_and_cycle_validation(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="categories-tree")
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[
            permission("product_categories", ActionType.CREATE),
            permission("product_categories", ActionType.READ),
            permission("product_categories", ActionType.UPDATE),
        ],
    )
    headers = auth_headers(user_access_token(actor))

    parent = await client.post(
        "/api/v1/product-categories",
        json={"name": "Food"},
        headers=headers,
    )
    child = await client.post(
        "/api/v1/product-categories",
        json={
            "name": "Rice",
            "parent_category_id": parent.json()["id"],
        },
        headers=headers,
    )
    assert parent.status_code == 201
    assert child.status_code == 201

    children = await client.get(
        f"/api/v1/product-categories?parent_category_id={parent.json()['id']}",
        headers=headers,
    )
    assert children.status_code == 200
    assert [item["id"] for item in children.json()["items"]] == [child.json()["id"]]

    self_parent = await client.patch(
        f"/api/v1/product-categories/{parent.json()['id']}",
        json={"parent_category_id": parent.json()["id"]},
        headers=headers,
    )
    cycle = await client.patch(
        f"/api/v1/product-categories/{parent.json()['id']}",
        json={"parent_category_id": child.json()["id"]},
        headers=headers,
    )

    assert self_parent.status_code == 400
    assert self_parent.json()["error_code"] == "invalid_parent_product_category"
    assert cycle.status_code == 400
    assert cycle.json()["error_code"] == "invalid_parent_product_category"


async def test_product_category_rejects_client_code(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="categories-conflict")
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("product_categories", ActionType.CREATE)],
    )
    headers = auth_headers(user_access_token(actor))
    response = await client.post(
        "/api/v1/product-categories",
        json={"code": "snacks", "name": "Snacks"},
        headers=headers,
    )

    assert response.status_code == 422


async def test_product_category_permission_denied_without_required_permission(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="categories-denied")
    actor = await make_user_with_permissions(db_session, tenant=tenant, permissions=[])

    response = await client.get(
        "/api/v1/product-categories",
        headers=auth_headers(user_access_token(actor)),
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "permission_denied"


async def test_seed_adds_product_category_permissions(db_session: AsyncSession) -> None:
    await _ensure_permissions(db_session)
    await _ensure_permissions(db_session)

    rows = await db_session.execute(
        select(Permission.code)
        .where(Permission.module == "product_categories")
        .order_by(Permission.code)
    )

    assert {code for (code,) in rows.all()} == {
        "product_categories.create",
        "product_categories.delete",
        "product_categories.read",
        "product_categories.update",
    }
