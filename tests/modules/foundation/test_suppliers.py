import uuid

from httpx import AsyncClient
from scripts.seed import _ensure_permissions
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.foundation_enums import PartyStatus, SupplierType
from src.modules.audit_logs.models import AuditLog
from src.modules.rbac.constants import ActionType
from src.modules.rbac.models import Permission
from src.modules.suppliers.models import Supplier

from tests.conftest import (
    auth_headers,
    make_tenant,
    make_user_with_permissions,
    permission,
    user_access_token,
)


async def test_supplier_crud_is_tenant_scoped_and_audited(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="suppliers-crud")
    other_tenant = await make_tenant(db_session, code="suppliers-other")
    other_supplier = await make_supplier(
        db_session,
        tenant_id=other_tenant.id,
        code="OTHER-SUPPLIER",
    )
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[
            permission("suppliers", ActionType.CREATE),
            permission("suppliers", ActionType.READ),
            permission("suppliers", ActionType.UPDATE),
            permission("suppliers", ActionType.DELETE),
        ],
    )
    headers = auth_headers(user_access_token(actor))

    created = await client.post(
        "/api/v1/suppliers",
        json={
            "name": "Yangon Grocery Wholesale",
            "supplier_type": "wholesaler",
            "phone": "+959987654321",
            "address": "Yangon",
        },
        headers=headers,
    )
    assert created.status_code == 201
    supplier_id = created.json()["id"]
    assert created.json()["code"].startswith("SUP-")

    listed = await client.get(
        "/api/v1/suppliers?search=Yangon&sort=code,id",
        headers=headers,
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [supplier_id]

    fetched = await client.get(f"/api/v1/suppliers/{supplier_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["tenant_id"] == str(tenant.id)
    assert fetched.json()["supplier_type"] == "wholesaler"

    not_found = await client.get(f"/api/v1/suppliers/{other_supplier.id}", headers=headers)
    assert not_found.status_code == 404

    updated = await client.patch(
        f"/api/v1/suppliers/{supplier_id}",
        json={"name": "Yangon Grocery Import", "supplier_type": "importer"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Yangon Grocery Import"
    assert updated.json()["supplier_type"] == "importer"

    deleted = await client.delete(f"/api/v1/suppliers/{supplier_id}", headers=headers)
    assert deleted.status_code == 204

    supplier = await db_session.scalar(
        select(Supplier).where(Supplier.id == uuid.UUID(supplier_id))
    )
    assert supplier is not None
    assert supplier.status == PartyStatus.INACTIVE

    actions = (
        (
            await db_session.execute(
                select(AuditLog.action).where(
                    AuditLog.tenant_id == tenant.id,
                    AuditLog.entity_id == supplier.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert actions == ["suppliers.create", "suppliers.update", "suppliers.deactivate"]


async def test_supplier_rejects_client_code(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="suppliers-conflict")
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("suppliers", ActionType.CREATE)],
    )

    response = await client.post(
        "/api/v1/suppliers",
        json={"code": "DUP", "name": "Duplicate"},
        headers=auth_headers(user_access_token(actor)),
    )

    assert response.status_code == 422


async def test_supplier_list_filters_and_sorting(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="suppliers-list")
    match = await make_supplier(
        db_session,
        tenant_id=tenant.id,
        code="B-SUP",
        name="Golden Manufacturer",
        supplier_type=SupplierType.MANUFACTURER,
        phone="555-987",
        address="Mandalay",
        status=PartyStatus.BLOCKED,
    )
    await make_supplier(
        db_session,
        tenant_id=tenant.id,
        code="A-SUP",
        name="Local Wholesale",
        supplier_type=SupplierType.LOCAL,
    )
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("suppliers", ActionType.READ)],
    )

    response = await client.get(
        (
            "/api/v1/suppliers"
            "?search=Mandalay"
            "&supplier_type=manufacturer"
            "&status=blocked"
            "&sort=-name,id"
        ),
        headers=auth_headers(user_access_token(actor)),
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [str(match.id)]


async def test_supplier_permission_denied_without_required_permission(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="suppliers-denied")
    actor = await make_user_with_permissions(db_session, tenant=tenant, permissions=[])

    response = await client.get(
        "/api/v1/suppliers",
        headers=auth_headers(user_access_token(actor)),
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "permission_denied"


async def test_seed_adds_supplier_permissions(db_session: AsyncSession) -> None:
    await _ensure_permissions(db_session)
    await _ensure_permissions(db_session)

    rows = await db_session.execute(
        select(Permission.code).where(Permission.module == "suppliers").order_by(Permission.code)
    )

    assert {code for (code,) in rows.all()} == {
        "suppliers.create",
        "suppliers.delete",
        "suppliers.read",
        "suppliers.update",
    }


async def make_supplier(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    code: str,
    name: str | None = None,
    supplier_type: SupplierType = SupplierType.LOCAL,
    phone: str | None = None,
    address: str | None = None,
    status: PartyStatus = PartyStatus.ACTIVE,
) -> Supplier:
    supplier = Supplier(
        tenant_id=tenant_id,
        code=code,
        name=name or code.title(),
        supplier_type=supplier_type,
        phone=phone,
        address=address,
        status=status,
    )
    db_session.add(supplier)
    await db_session.flush()
    return supplier
