import uuid
from datetime import UTC, datetime
from decimal import Decimal

from httpx import AsyncClient
from scripts.seed import _ensure_permissions
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.foundation_enums import CustomerType, PartyStatus, UnitKind
from src.modules.audit_logs.models import AuditLog
from src.modules.catalog.models import CatalogItem, ProductVariant, VariantUnit
from src.modules.customers.models import Customer
from src.modules.price_levels.models import PriceLevel
from src.modules.price_rules.models import PriceRule
from src.modules.price_rules.service import resolve_unit_price
from src.modules.rbac.constants import ActionType
from src.modules.rbac.models import Permission
from src.modules.units.models import Unit

from tests.conftest import (
    auth_headers,
    make_tenant,
    make_user_with_permissions,
    permission,
    user_access_token,
)


async def test_price_rule_crud_is_tenant_scoped_and_audited(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="price-rules-crud")
    other_tenant = await make_tenant(db_session, code="price-rules-other")
    setup = await make_price_rule_setup(db_session, tenant_id=tenant.id)
    other_setup = await make_price_rule_setup(
        db_session,
        tenant_id=other_tenant.id,
        unit_code="pr-other-unit",
        sku="PR-OTHER",
        price_level_code="other-price",
        customer_code="OTHER-CUSTOMER",
    )
    other_price_rule = await make_price_rule(
        db_session,
        tenant_id=other_tenant.id,
        product_variant_id=other_setup.variant.id,
        variant_unit_id=other_setup.variant_unit.id,
        price_level_id=other_setup.price_level.id,
    )
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[
            permission("price_rules", ActionType.CREATE),
            permission("price_rules", ActionType.READ),
            permission("price_rules", ActionType.UPDATE),
            permission("price_rules", ActionType.DELETE),
        ],
    )
    headers = auth_headers(user_access_token(actor))

    created = await client.post(
        "/api/v1/price-rules",
        json={
            "product_variant_id": str(setup.variant.id),
            "variant_unit_id": str(setup.variant_unit.id),
            "price_level_id": str(setup.price_level.id),
            "customer_id": str(setup.customer.id),
            "min_quantity": "1.00000000",
            "currency_code": "mmk",
            "unit_price": "2500.0000",
            "effective_from": "2026-08-08T00:00:00+00:00",
        },
        headers=headers,
    )
    assert created.status_code == 201
    price_rule_id = created.json()["id"]
    assert created.json()["currency_code"] == "MMK"

    listed = await client.get(
        (
            "/api/v1/price-rules"
            f"?product_variant_id={setup.variant.id}"
            f"&variant_unit_id={setup.variant_unit.id}"
            f"&price_level_id={setup.price_level.id}"
            f"&customer_id={setup.customer.id}"
            "&currency_code=mmk"
            "&is_active=true"
            "&effective_from_gte=2026-08-08"
            "&effective_from_lte=2026-08-08"
            "&sort=product_variant_id,effective_from,id"
        ),
        headers=headers,
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [price_rule_id]

    fetched = await client.get(f"/api/v1/price-rules/{price_rule_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["tenant_id"] == str(tenant.id)

    not_found = await client.get(f"/api/v1/price-rules/{other_price_rule.id}", headers=headers)
    assert not_found.status_code == 404

    updated = await client.patch(
        f"/api/v1/price-rules/{price_rule_id}",
        json={"unit_price": "2750.0000", "effective_to": "2026-12-31T00:00:00+00:00"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["unit_price"] == "2750.0000"

    deleted = await client.delete(f"/api/v1/price-rules/{price_rule_id}", headers=headers)
    assert deleted.status_code == 204

    price_rule = await db_session.scalar(
        select(PriceRule).where(PriceRule.id == uuid.UUID(price_rule_id))
    )
    assert price_rule is not None
    assert price_rule.is_active is False

    actions = (
        (
            await db_session.execute(
                select(AuditLog.action).where(
                    AuditLog.tenant_id == tenant.id,
                    AuditLog.entity_id == price_rule.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert actions == ["price_rules.create", "price_rules.update", "price_rules.deactivate"]


async def test_price_rule_overlap_rejects_exact_active_scope_only(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="price-rules-overlap")
    other_tenant = await make_tenant(db_session, code="price-rules-overlap-other")
    setup = await make_price_rule_setup(db_session, tenant_id=tenant.id)
    other_setup = await make_price_rule_setup(
        db_session,
        tenant_id=other_tenant.id,
        unit_code="pr-overlap-other-unit",
        sku="PR-OVERLAP-OTHER",
        price_level_code="other-retail",
        customer_code="OVERLAP-OTHER-CUSTOMER",
    )
    await make_price_rule(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.variant.id,
        variant_unit_id=setup.variant_unit.id,
        price_level_id=setup.price_level.id,
        customer_id=None,
        min_quantity=None,
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
        effective_to=None,
    )
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("price_rules", ActionType.CREATE)],
    )
    headers = auth_headers(user_access_token(actor))
    payload = {
        "product_variant_id": str(setup.variant.id),
        "variant_unit_id": str(setup.variant_unit.id),
        "price_level_id": str(setup.price_level.id),
        "unit_price": "1000.0000",
        "effective_from": "2026-06-01T00:00:00+00:00",
    }

    overlap = await client.post("/api/v1/price-rules", json=payload, headers=headers)
    quantity_specific = await client.post(
        "/api/v1/price-rules",
        json={**payload, "min_quantity": "10.00000000"},
        headers=headers,
    )
    customer_specific = await client.post(
        "/api/v1/price-rules",
        json={
            **payload,
            "customer_id": str(setup.customer.id),
            "effective_from": "2026-06-02T00:00:00+00:00",
        },
        headers=headers,
    )
    cross_tenant = await make_price_rule(
        db_session,
        tenant_id=other_tenant.id,
        product_variant_id=other_setup.variant.id,
        variant_unit_id=other_setup.variant_unit.id,
        price_level_id=other_setup.price_level.id,
        effective_from=datetime(2026, 6, 1, tzinfo=UTC),
    )

    assert overlap.status_code == 409
    assert overlap.json()["error_code"] == "price_rule_overlap_conflict"
    assert quantity_specific.status_code == 201
    assert customer_specific.status_code == 201
    assert cross_tenant.tenant_id == other_tenant.id


async def test_price_rule_allows_non_overlapping_windows(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="price-rules-non-overlap")
    setup = await make_price_rule_setup(db_session, tenant_id=tenant.id)
    await make_price_rule(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.variant.id,
        variant_unit_id=setup.variant_unit.id,
        price_level_id=setup.price_level.id,
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
        effective_to=datetime(2026, 6, 1, tzinfo=UTC),
    )
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("price_rules", ActionType.CREATE)],
    )

    response = await client.post(
        "/api/v1/price-rules",
        json={
            "product_variant_id": str(setup.variant.id),
            "variant_unit_id": str(setup.variant_unit.id),
            "price_level_id": str(setup.price_level.id),
            "unit_price": "1000.0000",
            "effective_from": "2026-06-01T00:00:00+00:00",
        },
        headers=auth_headers(user_access_token(actor)),
    )

    assert response.status_code == 201


async def test_price_rule_permission_denied_without_required_permission(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="price-rules-denied")
    actor = await make_user_with_permissions(db_session, tenant=tenant, permissions=[])

    response = await client.get(
        "/api/v1/price-rules",
        headers=auth_headers(user_access_token(actor)),
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "permission_denied"


async def test_price_rule_rejects_invalid_references(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="price-rules-invalid")
    other_tenant = await make_tenant(db_session, code="price-rules-invalid-other")
    setup = await make_price_rule_setup(db_session, tenant_id=tenant.id)
    inactive_variant = await make_variant(
        db_session,
        tenant_id=tenant.id,
        unit_id=setup.unit.id,
        sku="PR-INACTIVE",
        is_active=False,
    )
    other_setup = await make_price_rule_setup(
        db_session,
        tenant_id=other_tenant.id,
        unit_code="pr-invalid-other-unit",
        sku="PR-INVALID-OTHER",
        price_level_code="other-invalid",
        customer_code="INVALID-OTHER-CUSTOMER",
    )
    inactive_variant_unit = await make_variant_unit(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.variant.id,
        unit_id=setup.inactive_unit.id,
        is_active=False,
    )
    inactive_price_level = await make_price_level(
        db_session,
        tenant_id=tenant.id,
        code="inactive-pr-level",
        is_active=False,
    )
    inactive_customer = await make_customer(
        db_session,
        tenant_id=tenant.id,
        code="PR-INACTIVE-CUSTOMER",
        status=PartyStatus.INACTIVE,
    )
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("price_rules", ActionType.CREATE)],
    )
    headers = auth_headers(user_access_token(actor))
    payload = {
        "product_variant_id": str(setup.variant.id),
        "variant_unit_id": str(setup.variant_unit.id),
        "price_level_id": str(setup.price_level.id),
        "unit_price": "1000.0000",
        "effective_from": "2026-08-08T00:00:00+00:00",
    }

    inactive_variant_response = await client.post(
        "/api/v1/price-rules",
        json={**payload, "product_variant_id": str(inactive_variant.id)},
        headers=headers,
    )
    cross_variant_response = await client.post(
        "/api/v1/price-rules",
        json={**payload, "product_variant_id": str(other_setup.variant.id)},
        headers=headers,
    )
    inactive_variant_unit_response = await client.post(
        "/api/v1/price-rules",
        json={**payload, "variant_unit_id": str(inactive_variant_unit.id)},
        headers=headers,
    )
    cross_variant_unit_response = await client.post(
        "/api/v1/price-rules",
        json={**payload, "variant_unit_id": str(other_setup.variant_unit.id)},
        headers=headers,
    )
    inactive_price_level_response = await client.post(
        "/api/v1/price-rules",
        json={**payload, "price_level_id": str(inactive_price_level.id)},
        headers=headers,
    )
    cross_price_level_response = await client.post(
        "/api/v1/price-rules",
        json={**payload, "price_level_id": str(other_setup.price_level.id)},
        headers=headers,
    )
    inactive_customer_response = await client.post(
        "/api/v1/price-rules",
        json={**payload, "customer_id": str(inactive_customer.id)},
        headers=headers,
    )
    cross_customer_response = await client.post(
        "/api/v1/price-rules",
        json={**payload, "customer_id": str(other_setup.customer.id)},
        headers=headers,
    )

    assert inactive_variant_response.status_code == 400
    assert inactive_variant_response.json()["error_code"] == "invalid_price_rule_variant"
    assert cross_variant_response.status_code == 400
    assert cross_variant_response.json()["error_code"] == "invalid_price_rule_variant"
    assert inactive_variant_unit_response.status_code == 400
    assert inactive_variant_unit_response.json()["error_code"] == "invalid_price_rule_variant_unit"
    assert cross_variant_unit_response.status_code == 400
    assert cross_variant_unit_response.json()["error_code"] == "invalid_price_rule_variant_unit"
    assert inactive_price_level_response.status_code == 400
    assert inactive_price_level_response.json()["error_code"] == "invalid_price_rule_price_level"
    assert cross_price_level_response.status_code == 400
    assert cross_price_level_response.json()["error_code"] == "invalid_price_rule_price_level"
    assert inactive_customer_response.status_code == 400
    assert inactive_customer_response.json()["error_code"] == "invalid_price_rule_customer"
    assert cross_customer_response.status_code == 400
    assert cross_customer_response.json()["error_code"] == "invalid_price_rule_customer"


async def test_price_rule_numeric_and_date_validation(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="price-rules-validation")
    setup = await make_price_rule_setup(db_session, tenant_id=tenant.id)
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("price_rules", ActionType.CREATE)],
    )
    headers = auth_headers(user_access_token(actor))
    payload = {
        "product_variant_id": str(setup.variant.id),
        "variant_unit_id": str(setup.variant_unit.id),
        "price_level_id": str(setup.price_level.id),
        "unit_price": "1000.0000",
        "effective_from": "2026-08-08T00:00:00+00:00",
    }

    zero_price = await client.post(
        "/api/v1/price-rules",
        json={**payload, "unit_price": "0.0000"},
        headers=headers,
    )
    zero_quantity = await client.post(
        "/api/v1/price-rules",
        json={**payload, "min_quantity": "0.00000000"},
        headers=headers,
    )
    bad_dates = await client.post(
        "/api/v1/price-rules",
        json={**payload, "effective_to": "2026-08-07T00:00:00+00:00"},
        headers=headers,
    )
    naive_date = await client.post(
        "/api/v1/price-rules",
        json={**payload, "effective_from": "2026-08-08T00:00:00"},
        headers=headers,
    )

    assert zero_price.status_code == 422
    assert zero_quantity.status_code == 422
    assert bad_dates.status_code == 422
    assert naive_date.status_code == 422


async def test_resolve_unit_price_prefers_rules_then_variant_default(
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="price-rules-resolve")
    setup = await make_price_rule_setup(db_session, tenant_id=tenant.id)
    setup.variant.default_sale_price = Decimal("1200.0000")
    fallback_price, fallback_rule_id = await resolve_unit_price(
        db_session,
        tenant.id,
        product_variant_id=setup.variant.id,
        variant_unit_id=setup.variant_unit.id,
        price_level_id=setup.price_level.id,
        customer_id=None,
        quantity=Decimal("1.00000000"),
        effective_at=datetime(2026, 8, 8, tzinfo=UTC),
    )
    rule = await make_price_rule(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.variant.id,
        variant_unit_id=setup.variant_unit.id,
        price_level_id=setup.price_level.id,
        min_quantity=Decimal("10.00000000"),
        unit_price=Decimal("1000.0000"),
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
    )
    rule_price, rule_id = await resolve_unit_price(
        db_session,
        tenant.id,
        product_variant_id=setup.variant.id,
        variant_unit_id=setup.variant_unit.id,
        price_level_id=setup.price_level.id,
        customer_id=None,
        quantity=Decimal("12.00000000"),
        effective_at=datetime(2026, 8, 8, tzinfo=UTC),
    )

    assert fallback_price == Decimal("1200.0000")
    assert fallback_rule_id is None
    assert rule_price == Decimal("1000.0000")
    assert rule_id == rule.id


async def test_seed_adds_price_rule_permissions(db_session: AsyncSession) -> None:
    await _ensure_permissions(db_session)
    await _ensure_permissions(db_session)

    rows = await db_session.execute(
        select(Permission.code).where(Permission.module == "price_rules").order_by(Permission.code)
    )

    assert {code for (code,) in rows.all()} == {
        "price_rules.create",
        "price_rules.delete",
        "price_rules.read",
        "price_rules.update",
    }


class PriceRuleSetup:
    def __init__(
        self,
        *,
        unit: Unit,
        inactive_unit: Unit,
        variant: ProductVariant,
        variant_unit: VariantUnit,
        price_level: PriceLevel,
        customer: Customer,
    ) -> None:
        self.unit = unit
        self.inactive_unit = inactive_unit
        self.variant = variant
        self.variant_unit = variant_unit
        self.price_level = price_level
        self.customer = customer


async def make_price_rule_setup(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    unit_code: str = "pr-piece",
    sku: str = "PR-PRODUCT",
    price_level_code: str = "retail-pr",
    customer_code: str = "PR-CUSTOMER",
) -> PriceRuleSetup:
    unit = await make_unit(db_session, code=unit_code)
    inactive_unit = await make_unit(db_session, code=f"{unit_code}-inactive")
    variant = await make_variant(db_session, tenant_id=tenant_id, unit_id=unit.id, sku=sku)
    variant_unit = await make_variant_unit(
        db_session,
        tenant_id=tenant_id,
        product_variant_id=variant.id,
        unit_id=unit.id,
    )
    price_level = await make_price_level(
        db_session,
        tenant_id=tenant_id,
        code=price_level_code,
    )
    customer = await make_customer(db_session, tenant_id=tenant_id, code=customer_code)
    return PriceRuleSetup(
        unit=unit,
        inactive_unit=inactive_unit,
        variant=variant,
        variant_unit=variant_unit,
        price_level=price_level,
        customer=customer,
    )


async def make_unit(
    db_session: AsyncSession,
    *,
    code: str,
    is_active: bool = True,
) -> Unit:
    unit = Unit(code=code, name_en=code.title(), unit_kind=UnitKind.COUNT, is_active=is_active)
    db_session.add(unit)
    await db_session.flush()
    return unit


async def make_variant(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    unit_id: uuid.UUID,
    sku: str,
    is_active: bool = True,
) -> ProductVariant:
    item = CatalogItem(
        tenant_id=tenant_id,
        code=f"ITEM-{uuid.uuid4().hex[:8]}",
        name=sku.title(),
    )
    db_session.add(item)
    await db_session.flush()
    variant = ProductVariant(
        tenant_id=tenant_id,
        catalog_item_id=item.id,
        sku=sku,
        name="Default",
        base_unit_id=unit_id,
        is_active=is_active,
    )
    db_session.add(variant)
    await db_session.flush()
    return variant


async def make_variant_unit(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    unit_id: uuid.UUID,
    is_active: bool = True,
) -> VariantUnit:
    variant_unit = VariantUnit(
        tenant_id=tenant_id,
        product_variant_id=product_variant_id,
        unit_id=unit_id,
        conversion_to_base=Decimal("1.00000000"),
        is_sales_unit=True,
        is_active=is_active,
    )
    db_session.add(variant_unit)
    await db_session.flush()
    return variant_unit


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
    status: PartyStatus = PartyStatus.ACTIVE,
) -> Customer:
    customer = Customer(
        tenant_id=tenant_id,
        code=code,
        name=code.title(),
        customer_type=CustomerType.RETAIL,
        status=status,
    )
    db_session.add(customer)
    await db_session.flush()
    return customer


async def make_price_rule(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    variant_unit_id: uuid.UUID,
    price_level_id: uuid.UUID,
    customer_id: uuid.UUID | None = None,
    min_quantity: Decimal | None = None,
    unit_price: Decimal = Decimal("1000.0000"),
    effective_from: datetime = datetime(2026, 1, 1, tzinfo=UTC),
    effective_to: datetime | None = None,
    is_active: bool = True,
) -> PriceRule:
    price_rule = PriceRule(
        tenant_id=tenant_id,
        product_variant_id=product_variant_id,
        variant_unit_id=variant_unit_id,
        price_level_id=price_level_id,
        customer_id=customer_id,
        min_quantity=min_quantity,
        unit_price=unit_price,
        effective_from=effective_from,
        effective_to=effective_to,
        is_active=is_active,
    )
    db_session.add(price_rule)
    await db_session.flush()
    return price_rule
