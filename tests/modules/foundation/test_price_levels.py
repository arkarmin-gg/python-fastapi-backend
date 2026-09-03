from httpx import AsyncClient
from scripts.seed import _ensure_default_price_levels, _ensure_permissions
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.modules.audit_logs.models import AuditLog
from src.modules.price_levels.constants import DEFAULT_PRICE_LEVELS
from src.modules.price_levels.models import PriceLevel
from src.modules.rbac.constants import ActionType
from src.modules.rbac.models import Permission

from tests.conftest import (
    auth_headers,
    make_tenant,
    make_user_with_permissions,
    permission,
    user_access_token,
)


async def test_price_level_crud_is_tenant_scoped_and_audited(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="price-levels-crud")
    other_tenant = await make_tenant(db_session, code="price-levels-other")
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[
            permission("price_levels", ActionType.CREATE),
            permission("price_levels", ActionType.READ),
            permission("price_levels", ActionType.UPDATE),
            permission("price_levels", ActionType.DELETE),
        ],
    )
    other_price_level = PriceLevel(
        tenant_id=other_tenant.id,
        code="retail",
        name="Other Retail",
    )
    db_session.add(other_price_level)
    await db_session.flush()
    headers = auth_headers(user_access_token(actor))

    created = await client.post(
        "/api/v1/price-levels",
        json={
            "name": "Retail",
            "description": "Retail customers.",
            "is_default": True,
        },
        headers=headers,
    )
    assert created.status_code == 201
    price_level_id = created.json()["id"]
    assert created.json()["code"].startswith("PL-")

    listed = await client.get("/api/v1/price-levels?search=ret&sort=code", headers=headers)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [price_level_id]

    fetched = await client.get(f"/api/v1/price-levels/{price_level_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["tenant_id"] == str(tenant.id)

    not_found = await client.get(f"/api/v1/price-levels/{other_price_level.id}", headers=headers)
    assert not_found.status_code == 404

    updated = await client.patch(
        f"/api/v1/price-levels/{price_level_id}",
        json={"name": "Retail Customers"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Retail Customers"

    deleted = await client.delete(f"/api/v1/price-levels/{price_level_id}", headers=headers)
    assert deleted.status_code == 204

    price_level = await db_session.scalar(select(PriceLevel).where(PriceLevel.id == price_level_id))
    assert price_level is not None
    assert price_level.is_active is False
    assert price_level.is_default is False

    actions = (
        (
            await db_session.execute(
                select(AuditLog.action).where(
                    AuditLog.tenant_id == tenant.id,
                    AuditLog.entity_id == price_level.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert actions == [
        "price_levels.create",
        "price_levels.update",
        "price_levels.deactivate",
    ]


async def test_price_level_default_switches_within_tenant(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="price-levels-default")
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[
            permission("price_levels", ActionType.CREATE),
            permission("price_levels", ActionType.READ),
            permission("price_levels", ActionType.UPDATE),
        ],
    )
    headers = auth_headers(user_access_token(actor))

    retail = await client.post(
        "/api/v1/price-levels",
        json={"name": "Retail", "is_default": True},
        headers=headers,
    )
    wholesale = await client.post(
        "/api/v1/price-levels",
        json={"name": "Wholesale", "is_default": True},
        headers=headers,
    )
    assert retail.status_code == 201
    assert wholesale.status_code == 201

    defaults = await client.get("/api/v1/price-levels?is_default=true", headers=headers)
    assert defaults.status_code == 200
    assert defaults.json()["total"] == 1
    assert defaults.json()["items"][0]["id"] == wholesale.json()["id"]

    inactive_default = await client.patch(
        f"/api/v1/price-levels/{wholesale.json()['id']}",
        json={"is_active": False, "is_default": True},
        headers=headers,
    )
    assert inactive_default.status_code == 200
    assert inactive_default.json()["is_active"] is False
    assert inactive_default.json()["is_default"] is False


async def test_price_level_rejects_client_code(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="price-levels-conflict")
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("price_levels", ActionType.CREATE)],
    )
    headers = auth_headers(user_access_token(actor))
    response = await client.post(
        "/api/v1/price-levels",
        json={"code": "vip", "name": "VIP"},
        headers=headers,
    )

    assert response.status_code == 422


async def test_price_level_permission_denied_without_required_permission(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="price-levels-denied")
    actor = await make_user_with_permissions(db_session, tenant=tenant, permissions=[])

    response = await client.get(
        "/api/v1/price-levels",
        headers=auth_headers(user_access_token(actor)),
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "permission_denied"


async def test_seed_adds_price_levels_and_permissions_idempotently(
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="price-levels-seed")
    await _ensure_permissions(db_session)
    await _ensure_permissions(db_session)
    price_levels_first = await _ensure_default_price_levels(db_session, tenant)
    price_levels_second = await _ensure_default_price_levels(db_session, tenant)

    permission_rows = await db_session.execute(
        select(Permission.code).where(Permission.module == "price_levels").order_by(Permission.code)
    )
    price_level_rows = await db_session.execute(
        select(PriceLevel.code).where(PriceLevel.tenant_id == tenant.id).order_by(PriceLevel.code)
    )

    assert len(price_levels_first) == len(DEFAULT_PRICE_LEVELS)
    assert len(price_levels_second) == len(DEFAULT_PRICE_LEVELS)
    assert {code for (code,) in price_level_rows.all()} == {
        price_level["code"] for price_level in DEFAULT_PRICE_LEVELS
    }
    assert {code for (code,) in permission_rows.all()} == {
        "price_levels.create",
        "price_levels.delete",
        "price_levels.read",
        "price_levels.update",
    }
