import uuid
from decimal import Decimal

from httpx import AsyncClient
from scripts.seed import _ensure_permissions
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.foundation_enums import CustomerType, PartyStatus
from src.modules.audit_logs.models import AuditLog
from src.modules.customers.models import Customer
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


async def test_customer_crud_is_tenant_scoped_and_audited(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="customers-crud")
    other_tenant = await make_tenant(db_session, code="customers-other")
    price_level = await make_price_level(db_session, tenant_id=tenant.id, code="retail")
    other_customer = await make_customer(
        db_session,
        tenant_id=other_tenant.id,
        code="OTHER-CUSTOMER",
    )
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[
            permission("customers", ActionType.CREATE),
            permission("customers", ActionType.READ),
            permission("customers", ActionType.UPDATE),
            permission("customers", ActionType.DELETE),
        ],
    )
    headers = auth_headers(user_access_token(actor))

    created = await client.post(
        "/api/v1/customers",
        json={
            "name": "Aye Aye Store",
            "customer_type": "retail",
            "price_level_id": str(price_level.id),
            "phone": "+959123456789",
            "address": "Yangon",
            "credit_limit": "500000.0000",
        },
        headers=headers,
    )
    assert created.status_code == 201
    customer_id = created.json()["id"]
    assert created.json()["code"].startswith("CUS-")

    listed = await client.get(
        "/api/v1/customers?search=Aye&sort=code,id",
        headers=headers,
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [customer_id]

    fetched = await client.get(f"/api/v1/customers/{customer_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["tenant_id"] == str(tenant.id)
    assert fetched.json()["price_level_id"] == str(price_level.id)

    not_found = await client.get(f"/api/v1/customers/{other_customer.id}", headers=headers)
    assert not_found.status_code == 404

    updated = await client.patch(
        f"/api/v1/customers/{customer_id}",
        json={"name": "Aye Aye Wholesale", "customer_type": "wholesale"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Aye Aye Wholesale"
    assert updated.json()["customer_type"] == "wholesale"

    deleted = await client.delete(f"/api/v1/customers/{customer_id}", headers=headers)
    assert deleted.status_code == 204

    customer = await db_session.scalar(
        select(Customer).where(Customer.id == uuid.UUID(customer_id))
    )
    assert customer is not None
    assert customer.status == PartyStatus.INACTIVE

    actions = (
        (
            await db_session.execute(
                select(AuditLog.action).where(
                    AuditLog.tenant_id == tenant.id,
                    AuditLog.entity_id == customer.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert actions == ["customers.create", "customers.update", "customers.deactivate"]


async def test_customer_rejects_client_code(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="customers-conflict")
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("customers", ActionType.CREATE)],
    )

    response = await client.post(
        "/api/v1/customers",
        json={"code": "DUP", "name": "Duplicate"},
        headers=auth_headers(user_access_token(actor)),
    )

    assert response.status_code == 422


async def test_customer_list_filters_and_sorting(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="customers-list")
    retail = await make_price_level(db_session, tenant_id=tenant.id, code="retail-list")
    wholesale = await make_price_level(db_session, tenant_id=tenant.id, code="wholesale-list")
    match = await make_customer(
        db_session,
        tenant_id=tenant.id,
        code="B-CUST",
        name="Golden Restaurant",
        customer_type=CustomerType.RESTAURANT,
        price_level_id=wholesale.id,
        phone="555-123",
        address="Mandalay",
        status=PartyStatus.BLOCKED,
    )
    await make_customer(
        db_session,
        tenant_id=tenant.id,
        code="A-CUST",
        name="Retail Walk In",
        customer_type=CustomerType.RETAIL,
        price_level_id=retail.id,
    )
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("customers", ActionType.READ)],
    )

    response = await client.get(
        (
            "/api/v1/customers"
            "?search=Mandalay"
            "&customer_type=restaurant"
            f"&price_level_id={wholesale.id}"
            "&status=blocked"
            "&sort=-name,id"
        ),
        headers=auth_headers(user_access_token(actor)),
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [str(match.id)]


async def test_customer_permission_denied_without_required_permission(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="customers-denied")
    actor = await make_user_with_permissions(db_session, tenant=tenant, permissions=[])

    response = await client.get(
        "/api/v1/customers",
        headers=auth_headers(user_access_token(actor)),
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "permission_denied"


async def test_customer_rejects_invalid_price_levels(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="customers-invalid-price")
    other_tenant = await make_tenant(db_session, code="customers-invalid-price-other")
    inactive_price_level = await make_price_level(
        db_session,
        tenant_id=tenant.id,
        code="inactive",
        is_active=False,
    )
    other_price_level = await make_price_level(
        db_session,
        tenant_id=other_tenant.id,
        code="other",
    )
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("customers", ActionType.CREATE)],
    )
    headers = auth_headers(user_access_token(actor))
    payload = {"name": "Bad Price Customer"}

    missing = await client.post(
        "/api/v1/customers",
        json={**payload, "price_level_id": str(uuid.uuid4())},
        headers=headers,
    )
    inactive = await client.post(
        "/api/v1/customers",
        json={**payload, "price_level_id": str(inactive_price_level.id)},
        headers=headers,
    )
    cross_tenant = await client.post(
        "/api/v1/customers",
        json={**payload, "price_level_id": str(other_price_level.id)},
        headers=headers,
    )

    assert missing.status_code == 400
    assert missing.json()["error_code"] == "invalid_customer_price_level"
    assert inactive.status_code == 400
    assert inactive.json()["error_code"] == "invalid_customer_price_level"
    assert cross_tenant.status_code == 400
    assert cross_tenant.json()["error_code"] == "invalid_customer_price_level"


async def test_customer_credit_limit_validation(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="customers-credit-limit")
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("customers", ActionType.CREATE)],
    )

    response = await client.post(
        "/api/v1/customers",
        json={"name": "Negative Credit", "credit_limit": "-1.0000"},
        headers=auth_headers(user_access_token(actor)),
    )

    assert response.status_code == 422


async def test_seed_adds_customer_permissions(db_session: AsyncSession) -> None:
    await _ensure_permissions(db_session)
    await _ensure_permissions(db_session)

    rows = await db_session.execute(
        select(Permission.code).where(Permission.module == "customers").order_by(Permission.code)
    )

    assert {code for (code,) in rows.all()} == {
        "customers.create",
        "customers.delete",
        "customers.read",
        "customers.update",
    }


async def make_price_level(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    code: str,
    is_active: bool = True,
) -> PriceLevel:
    price_level = PriceLevel(
        tenant_id=tenant_id,
        code=code,
        name=code.title(),
        is_active=is_active,
    )
    db_session.add(price_level)
    await db_session.flush()
    return price_level


async def make_customer(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    code: str,
    name: str | None = None,
    customer_type: CustomerType = CustomerType.RETAIL,
    price_level_id: uuid.UUID | None = None,
    phone: str | None = None,
    address: str | None = None,
    credit_limit: Decimal | None = None,
    status: PartyStatus = PartyStatus.ACTIVE,
) -> Customer:
    customer = Customer(
        tenant_id=tenant_id,
        code=code,
        name=name or code.title(),
        customer_type=customer_type,
        price_level_id=price_level_id,
        phone=phone,
        address=address,
        credit_limit=credit_limit,
        status=status,
    )
    db_session.add(customer)
    await db_session.flush()
    return customer
