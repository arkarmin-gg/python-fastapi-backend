import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.foundation_enums import (
    LocationType,
    SourceType,
    StockBatchStatus,
    UnitKind,
)
from src.modules.catalog.models import CatalogItem, ProductVariant, VariantBarcode, VariantUnit
from src.modules.inventory.models import StockBalance, StockBatch
from src.modules.locations.models import Location
from src.modules.product_categories.models import ProductCategory
from src.modules.rbac.constants import ActionType
from src.modules.units.models import Unit

from tests.conftest import (
    auth_headers,
    make_tenant,
    make_user_with_permissions,
    permission,
    user_access_token,
)


async def test_list_stock_balances_hides_zero_and_inactive_batches_by_default(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="inv-defaults")
    other_tenant = await make_tenant(db_session, code="inv-defaults-other")
    unit = await make_unit(db_session, code="inv-pcs")
    catalog_item = await make_catalog_item(db_session, tenant_id=tenant.id, name="Widget")
    variant = await make_product_variant(
        db_session, tenant_id=tenant.id, catalog_item_id=catalog_item.id, sku="INV-1", unit=unit
    )
    location = await make_location(db_session, tenant_id=tenant.id, code="INV-WH")

    active_batch = await make_stock_batch(
        db_session, tenant_id=tenant.id, product_variant_id=variant.id
    )
    zero_batch = await make_stock_batch(
        db_session, tenant_id=tenant.id, product_variant_id=variant.id
    )
    cancelled_batch = await make_stock_batch(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=variant.id,
        status=StockBatchStatus.CANCELLED,
    )
    visible_balance = await make_stock_balance(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=variant.id,
        location_id=location.id,
        stock_batch_id=active_batch.id,
        quantity_base=Decimal("10.00000000"),
    )
    await make_stock_balance(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=variant.id,
        location_id=location.id,
        stock_batch_id=zero_batch.id,
        quantity_base=Decimal("0.00000000"),
    )
    await make_stock_balance(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=variant.id,
        location_id=location.id,
        stock_batch_id=cancelled_batch.id,
        quantity_base=Decimal("5.00000000"),
    )

    other_setup_variant = await make_product_variant(
        db_session,
        tenant_id=other_tenant.id,
        catalog_item_id=(
            await make_catalog_item(db_session, tenant_id=other_tenant.id, name="Other")
        ).id,
        sku="INV-OTHER",
        unit=await make_unit(db_session, code="inv-other-unit"),
    )
    other_location = await make_location(db_session, tenant_id=other_tenant.id, code="INV-OTHER-WH")
    other_batch = await make_stock_batch(
        db_session, tenant_id=other_tenant.id, product_variant_id=other_setup_variant.id
    )
    other_balance = await make_stock_balance(
        db_session,
        tenant_id=other_tenant.id,
        product_variant_id=other_setup_variant.id,
        location_id=other_location.id,
        stock_batch_id=other_batch.id,
        quantity_base=Decimal("99.00000000"),
    )
    actor = await make_reader(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    listed = await client.get("/api/v1/stock-balances", headers=headers)
    assert listed.status_code == 200
    body = listed.json()
    assert [item["id"] for item in body["items"]] == [str(visible_balance.id)]
    item = body["items"][0]
    assert item["quantity_base"] == "10.00000000"
    assert item["unit_code"] == "inv-pcs"
    assert item["unit_name"] == "Inv-Pcs"
    assert item["display_quantity"] is None

    fetched = await client.get(f"/api/v1/stock-balances/{visible_balance.id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["unit_id"] == str(unit.id)

    not_found = await client.get(f"/api/v1/stock-balances/{other_balance.id}", headers=headers)
    assert not_found.status_code == 404


async def test_list_stock_balances_include_zero_and_batch_status_override(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="inv-batch-status")
    unit = await make_unit(db_session, code="inv-bs-unit")
    catalog_item = await make_catalog_item(db_session, tenant_id=tenant.id, name="Gadget")
    variant = await make_product_variant(
        db_session, tenant_id=tenant.id, catalog_item_id=catalog_item.id, sku="INV-BS", unit=unit
    )
    location = await make_location(db_session, tenant_id=tenant.id, code="INV-BS-WH")
    zero_batch = await make_stock_batch(
        db_session, tenant_id=tenant.id, product_variant_id=variant.id
    )
    depleted_batch = await make_stock_batch(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=variant.id,
        status=StockBatchStatus.DEPLETED,
    )
    zero_balance = await make_stock_balance(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=variant.id,
        location_id=location.id,
        stock_batch_id=zero_batch.id,
        quantity_base=Decimal("0.00000000"),
    )
    depleted_balance = await make_stock_balance(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=variant.id,
        location_id=location.id,
        stock_batch_id=depleted_batch.id,
        quantity_base=Decimal("2.00000000"),
    )
    actor = await make_reader(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    include_zero = await client.get(
        "/api/v1/stock-balances?include_zero=true&batch_status=all", headers=headers
    )
    assert include_zero.status_code == 200
    ids = {item["id"] for item in include_zero.json()["items"]}
    assert ids == {str(zero_balance.id), str(depleted_balance.id)}

    depleted_only = await client.get(
        "/api/v1/stock-balances?include_zero=true&batch_status=depleted", headers=headers
    )
    assert depleted_only.status_code == 200
    assert [item["id"] for item in depleted_only.json()["items"]] == [str(depleted_balance.id)]


async def test_list_stock_balances_search_and_category_filters(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="inv-search")
    unit = await make_unit(db_session, code="inv-search-unit")
    beverages = await make_category(db_session, tenant_id=tenant.id, name="Beverages")
    snacks = await make_category(db_session, tenant_id=tenant.id, name="Snacks")
    milk_item = await make_catalog_item(
        db_session, tenant_id=tenant.id, name="Milk 1L", category_id=beverages.id
    )
    chips_item = await make_catalog_item(
        db_session, tenant_id=tenant.id, name="Chips", category_id=snacks.id
    )
    milk = await make_product_variant(
        db_session, tenant_id=tenant.id, catalog_item_id=milk_item.id, sku="MILK-1L", unit=unit
    )
    chips = await make_product_variant(
        db_session, tenant_id=tenant.id, catalog_item_id=chips_item.id, sku="CHIPS-1", unit=unit
    )
    await make_barcode(
        db_session, tenant_id=tenant.id, product_variant_id=milk.id, barcode="8801234567890"
    )
    location = await make_location(db_session, tenant_id=tenant.id, code="INV-SEARCH-WH")
    milk_batch = await make_stock_batch(db_session, tenant_id=tenant.id, product_variant_id=milk.id)
    chips_batch = await make_stock_batch(
        db_session, tenant_id=tenant.id, product_variant_id=chips.id
    )
    milk_balance = await make_stock_balance(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=milk.id,
        location_id=location.id,
        stock_batch_id=milk_batch.id,
        quantity_base=Decimal("4.00000000"),
    )
    await make_stock_balance(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=chips.id,
        location_id=location.id,
        stock_batch_id=chips_batch.id,
        quantity_base=Decimal("6.00000000"),
    )
    actor = await make_reader(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    by_name = await client.get("/api/v1/stock-balances?search=milk", headers=headers)
    assert [item["id"] for item in by_name.json()["items"]] == [str(milk_balance.id)]

    by_barcode = await client.get("/api/v1/stock-balances?search=8801234567890", headers=headers)
    assert [item["id"] for item in by_barcode.json()["items"]] == [str(milk_balance.id)]

    by_category = await client.get(
        f"/api/v1/stock-balances?category_id={beverages.id}", headers=headers
    )
    assert [item["id"] for item in by_category.json()["items"]] == [str(milk_balance.id)]


async def test_list_stock_balances_sort_by_name_and_expiry(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="inv-sort")
    unit = await make_unit(db_session, code="inv-sort-unit")
    location_a = await make_location(db_session, tenant_id=tenant.id, code="INV-SORT-A")
    location_b = await make_location(db_session, tenant_id=tenant.id, code="INV-SORT-B")
    zebra_item = await make_catalog_item(db_session, tenant_id=tenant.id, name="Zebra")
    apple_item = await make_catalog_item(db_session, tenant_id=tenant.id, name="Apple")
    zebra = await make_product_variant(
        db_session, tenant_id=tenant.id, catalog_item_id=zebra_item.id, sku="ZEBRA", unit=unit
    )
    apple = await make_product_variant(
        db_session, tenant_id=tenant.id, catalog_item_id=apple_item.id, sku="APPLE", unit=unit
    )
    zebra_batch = await make_stock_batch(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=zebra.id,
        expiry_date=date(2026, 12, 1),
    )
    apple_batch = await make_stock_batch(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=apple.id,
        expiry_date=date(2026, 9, 1),
    )
    zebra_balance = await make_stock_balance(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=zebra.id,
        location_id=location_a.id,
        stock_batch_id=zebra_batch.id,
        quantity_base=Decimal("1.00000000"),
    )
    apple_balance = await make_stock_balance(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=apple.id,
        location_id=location_b.id,
        stock_batch_id=apple_batch.id,
        quantity_base=Decimal("1.00000000"),
    )
    actor = await make_reader(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    by_name = await client.get("/api/v1/stock-balances?sort=product_variant_name", headers=headers)
    assert [item["id"] for item in by_name.json()["items"]] == [
        str(apple_balance.id),
        str(zebra_balance.id),
    ]

    by_expiry = await client.get("/api/v1/stock-balances?sort=expiry_date", headers=headers)
    assert [item["id"] for item in by_expiry.json()["items"]] == [
        str(apple_balance.id),
        str(zebra_balance.id),
    ]


async def test_list_stock_balances_group_by_product_variant_and_location(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="inv-group")
    unit = await make_unit(db_session, code="inv-group-unit")
    catalog_item = await make_catalog_item(db_session, tenant_id=tenant.id, name="Rice")
    variant = await make_product_variant(
        db_session, tenant_id=tenant.id, catalog_item_id=catalog_item.id, sku="RICE-1", unit=unit
    )
    location_a = await make_location(db_session, tenant_id=tenant.id, code="INV-GROUP-A")
    location_b = await make_location(db_session, tenant_id=tenant.id, code="INV-GROUP-B")
    batch_1 = await make_stock_batch(db_session, tenant_id=tenant.id, product_variant_id=variant.id)
    batch_2 = await make_stock_batch(db_session, tenant_id=tenant.id, product_variant_id=variant.id)
    await make_stock_balance(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=variant.id,
        location_id=location_a.id,
        stock_batch_id=batch_1.id,
        quantity_base=Decimal("10.00000000"),
    )
    await make_stock_balance(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=variant.id,
        location_id=location_a.id,
        stock_batch_id=batch_2.id,
        quantity_base=Decimal("5.00000000"),
    )
    await make_stock_balance(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=variant.id,
        location_id=location_b.id,
        stock_batch_id=batch_1.id,
        quantity_base=Decimal("3.00000000"),
    )
    actor = await make_reader(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    by_variant = await client.get(
        "/api/v1/stock-balances?group_by=product_variant", headers=headers
    )
    assert by_variant.status_code == 200
    variant_items = by_variant.json()["items"]
    assert len(variant_items) == 1
    assert variant_items[0]["product_variant_id"] == str(variant.id)
    assert variant_items[0]["quantity_base"] == "18.00000000"
    assert variant_items[0]["location_id"] is None
    assert variant_items[0]["unit_code"] == "inv-group-unit"
    assert "stock_batch_id" not in variant_items[0]

    by_variant_location = await client.get(
        "/api/v1/stock-balances?group_by=product_variant_location&sort=location_name",
        headers=headers,
    )
    assert by_variant_location.status_code == 200
    grouped_items = by_variant_location.json()["items"]
    totals = {item["location_id"]: item["quantity_base"] for item in grouped_items}
    assert totals == {
        str(location_a.id): "15.00000000",
        str(location_b.id): "3.00000000",
    }


async def test_list_stock_balances_display_unit_conversion(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="inv-display-unit")
    piece_unit = await make_unit(db_session, code="inv-pc")
    dozen_unit = await make_unit(db_session, code="inv-dozen")
    catalog_item = await make_catalog_item(db_session, tenant_id=tenant.id, name="Eggs")
    variant = await make_product_variant(
        db_session,
        tenant_id=tenant.id,
        catalog_item_id=catalog_item.id,
        sku="EGGS-1",
        unit=piece_unit,
    )
    await make_variant_unit(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=variant.id,
        unit_id=dozen_unit.id,
        conversion_to_base=Decimal("12.00000000"),
        is_base_unit=False,
        rounding_precision=Decimal("0.01"),
    )
    other_item = await make_catalog_item(db_session, tenant_id=tenant.id, name="Bread")
    other_variant = await make_product_variant(
        db_session,
        tenant_id=tenant.id,
        catalog_item_id=other_item.id,
        sku="BREAD-1",
        unit=piece_unit,
    )
    location = await make_location(db_session, tenant_id=tenant.id, code="INV-DISPLAY-WH")
    eggs_batch = await make_stock_batch(
        db_session, tenant_id=tenant.id, product_variant_id=variant.id
    )
    bread_batch = await make_stock_batch(
        db_session, tenant_id=tenant.id, product_variant_id=other_variant.id
    )
    eggs_balance = await make_stock_balance(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=variant.id,
        location_id=location.id,
        stock_batch_id=eggs_batch.id,
        quantity_base=Decimal("30.00000000"),
    )
    bread_balance = await make_stock_balance(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=other_variant.id,
        location_id=location.id,
        stock_batch_id=bread_batch.id,
        quantity_base=Decimal("7.00000000"),
    )
    actor = await make_reader(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    response = await client.get(
        f"/api/v1/stock-balances?display_unit_id={dozen_unit.id}", headers=headers
    )
    assert response.status_code == 200
    items = {item["id"]: item for item in response.json()["items"]}
    assert items[str(eggs_balance.id)]["display_quantity"] == "2.5"
    assert items[str(eggs_balance.id)]["display_unit_code"] == "inv-dozen"
    assert items[str(bread_balance.id)]["display_quantity"] is None
    assert items[str(bread_balance.id)]["display_unit_code"] is None


async def test_list_stock_balances_auto_resolved_purchase_unit(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="inv-purchase-unit")
    piece_unit = await make_unit(db_session, code="inv-pu-pc")
    dozen_unit = await make_unit(db_session, code="inv-pu-dozen")
    bag_unit = await make_unit(db_session, code="inv-pu-bag")
    case_unit = await make_unit(db_session, code="inv-pu-case")
    location = await make_location(db_session, tenant_id=tenant.id, code="INV-PU-WH")

    # Eggs: one purchase-flagged unit (dozen, conversion 12) -> populated.
    eggs_item = await make_catalog_item(db_session, tenant_id=tenant.id, name="Eggs")
    eggs_variant = await make_product_variant(
        db_session,
        tenant_id=tenant.id,
        catalog_item_id=eggs_item.id,
        sku="PU-EGGS-1",
        unit=piece_unit,
    )
    await make_variant_unit(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=eggs_variant.id,
        unit_id=dozen_unit.id,
        conversion_to_base=Decimal("12.00000000"),
        rounding_precision=Decimal("0.01"),
        is_purchase_unit=True,
    )
    eggs_batch = await make_stock_batch(
        db_session, tenant_id=tenant.id, product_variant_id=eggs_variant.id
    )
    eggs_balance = await make_stock_balance(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=eggs_variant.id,
        location_id=location.id,
        stock_batch_id=eggs_batch.id,
        quantity_base=Decimal("30.00000000"),
    )

    # Bread: no purchase-flagged unit at all -> null. `make_product_variant`
    # auto-creates a base VariantUnit with `is_purchase_unit=True` (matching
    # this app's real default), so explicitly flip it off here to exercise
    # the "nothing resolves" fallback path.
    bread_item = await make_catalog_item(db_session, tenant_id=tenant.id, name="Bread")
    bread_variant = await make_product_variant(
        db_session,
        tenant_id=tenant.id,
        catalog_item_id=bread_item.id,
        sku="PU-BREAD-1",
        unit=piece_unit,
    )
    bread_base_unit = (
        await db_session.scalars(
            select(VariantUnit).where(VariantUnit.product_variant_id == bread_variant.id)
        )
    ).one()
    bread_base_unit.is_purchase_unit = False
    await db_session.flush()
    bread_batch = await make_stock_batch(
        db_session, tenant_id=tenant.id, product_variant_id=bread_variant.id
    )
    bread_balance = await make_stock_balance(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=bread_variant.id,
        location_id=location.id,
        stock_batch_id=bread_batch.id,
        quantity_base=Decimal("7.00000000"),
    )

    # Sugar: two purchase-flagged units (bag=20, case=200) -> larger (case) wins.
    sugar_item = await make_catalog_item(db_session, tenant_id=tenant.id, name="Sugar")
    sugar_variant = await make_product_variant(
        db_session,
        tenant_id=tenant.id,
        catalog_item_id=sugar_item.id,
        sku="PU-SUGAR-1",
        unit=piece_unit,
    )
    await make_variant_unit(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=sugar_variant.id,
        unit_id=bag_unit.id,
        conversion_to_base=Decimal("20.00000000"),
        rounding_precision=Decimal("0.01"),
        is_purchase_unit=True,
    )
    await make_variant_unit(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=sugar_variant.id,
        unit_id=case_unit.id,
        conversion_to_base=Decimal("200.00000000"),
        rounding_precision=Decimal("0.01"),
        is_purchase_unit=True,
    )
    sugar_batch = await make_stock_batch(
        db_session, tenant_id=tenant.id, product_variant_id=sugar_variant.id
    )
    sugar_balance = await make_stock_balance(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=sugar_variant.id,
        location_id=location.id,
        stock_batch_id=sugar_batch.id,
        quantity_base=Decimal("100.00000000"),
    )

    actor = await make_reader(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    # Also pass an unrelated display_unit_id (dozen) to confirm the two
    # resolution mechanisms are independent: dozen only matches Eggs, but
    # purchase_unit fields must still populate for Sugar regardless.
    response = await client.get(
        f"/api/v1/stock-balances?display_unit_id={dozen_unit.id}", headers=headers
    )
    assert response.status_code == 200
    items = {item["id"]: item for item in response.json()["items"]}

    eggs_item_out = items[str(eggs_balance.id)]
    assert eggs_item_out["purchase_unit_quantity"] == "2.5"
    assert eggs_item_out["purchase_unit_code"] == "inv-pu-dozen"
    assert eggs_item_out["display_quantity"] == "2.5"
    assert eggs_item_out["display_unit_code"] == "inv-pu-dozen"

    bread_item_out = items[str(bread_balance.id)]
    assert bread_item_out["purchase_unit_quantity"] is None
    assert bread_item_out["purchase_unit_id"] is None
    assert bread_item_out["purchase_unit_code"] is None
    assert bread_item_out["purchase_unit_name"] is None

    sugar_item_out = items[str(sugar_balance.id)]
    assert sugar_item_out["purchase_unit_quantity"] == "0.5"
    assert sugar_item_out["purchase_unit_code"] == "inv-pu-case"
    assert sugar_item_out["display_quantity"] is None
    assert sugar_item_out["display_unit_code"] is None


async def test_stock_balances_require_inventory_read_permission(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="inv-permissions")
    forbidden_user = await make_user_with_permissions(db_session, tenant=tenant, permissions=[])
    headers = auth_headers(user_access_token(forbidden_user))

    response = await client.get("/api/v1/stock-balances", headers=headers)
    assert response.status_code == 403


async def make_reader(db_session: AsyncSession, *, tenant):
    return await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("inventory", ActionType.READ)],
    )


async def make_unit(db_session: AsyncSession, *, code: str) -> Unit:
    unit = Unit(code=code, name_en=code.title(), unit_kind=UnitKind.COUNT)
    db_session.add(unit)
    await db_session.flush()
    return unit


async def make_category(
    db_session: AsyncSession, *, tenant_id: uuid.UUID, name: str
) -> ProductCategory:
    category = ProductCategory(tenant_id=tenant_id, name=name)
    db_session.add(category)
    await db_session.flush()
    return category


async def make_catalog_item(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    name: str,
    category_id: uuid.UUID | None = None,
) -> CatalogItem:
    catalog_item = CatalogItem(
        tenant_id=tenant_id,
        code=f"ITEM-{uuid.uuid4().hex[:8]}",
        name=name,
        category_id=category_id,
    )
    db_session.add(catalog_item)
    await db_session.flush()
    return catalog_item


async def make_product_variant(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    catalog_item_id: uuid.UUID,
    sku: str,
    unit: Unit,
    is_active: bool = True,
) -> ProductVariant:
    product_variant = ProductVariant(
        tenant_id=tenant_id,
        catalog_item_id=catalog_item_id,
        sku=sku,
        name=sku.title(),
        base_unit_id=unit.id,
        is_active=is_active,
    )
    db_session.add(product_variant)
    await db_session.flush()
    await make_variant_unit(
        db_session,
        tenant_id=tenant_id,
        product_variant_id=product_variant.id,
        unit_id=unit.id,
        conversion_to_base=Decimal("1.00000000"),
        is_base_unit=True,
    )
    return product_variant


async def make_variant_unit(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    unit_id: uuid.UUID,
    conversion_to_base: Decimal = Decimal("1.00000000"),
    is_base_unit: bool = False,
    rounding_precision: Decimal = Decimal("0.000001"),
    is_active: bool = True,
    is_purchase_unit: bool = True,
) -> VariantUnit:
    variant_unit = VariantUnit(
        tenant_id=tenant_id,
        product_variant_id=product_variant_id,
        unit_id=unit_id,
        conversion_to_base=conversion_to_base,
        is_base_unit=is_base_unit,
        is_purchase_unit=is_purchase_unit,
        is_sales_unit=True,
        rounding_precision=rounding_precision,
        is_active=is_active,
    )
    db_session.add(variant_unit)
    await db_session.flush()
    return variant_unit


async def make_barcode(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    barcode: str,
    is_active: bool = True,
) -> VariantBarcode:
    record = VariantBarcode(
        tenant_id=tenant_id,
        product_variant_id=product_variant_id,
        barcode=barcode,
        is_active=is_active,
    )
    db_session.add(record)
    await db_session.flush()
    return record


async def make_location(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    code: str,
    is_active: bool = True,
) -> Location:
    location = Location(
        tenant_id=tenant_id,
        code=code,
        name=code.title(),
        location_type=LocationType.WAREHOUSE,
        is_active=is_active,
    )
    db_session.add(location)
    await db_session.flush()
    return location


async def make_stock_batch(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    status: StockBatchStatus = StockBatchStatus.ACTIVE,
    expiry_date: date | None = None,
    unit_cost_base: Decimal = Decimal("10.00000000"),
) -> StockBatch:
    now = datetime.now(UTC)
    batch = StockBatch(
        tenant_id=tenant_id,
        product_variant_id=product_variant_id,
        source_type=SourceType.MANUAL,
        source_id=uuid.uuid4(),
        received_at=now - timedelta(days=1),
        expiry_date=expiry_date,
        initial_quantity_base=Decimal("0.00000000"),
        unit_cost_base=unit_cost_base,
        total_cost=Decimal("0.0000"),
        conversion_to_base=Decimal("1.00000000"),
        status=status,
        created_at=now,
    )
    db_session.add(batch)
    await db_session.flush()
    return batch


async def make_stock_balance(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    location_id: uuid.UUID,
    stock_batch_id: uuid.UUID,
    quantity_base: Decimal,
) -> StockBalance:
    balance = StockBalance(
        tenant_id=tenant_id,
        product_variant_id=product_variant_id,
        location_id=location_id,
        stock_batch_id=stock_batch_id,
        quantity_base=quantity_base,
        updated_at=datetime.now(UTC),
    )
    db_session.add(balance)
    await db_session.flush()
    return balance
