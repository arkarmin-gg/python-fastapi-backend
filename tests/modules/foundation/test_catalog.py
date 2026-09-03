import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from scripts.seed import _ensure_permissions
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.foundation_enums import LocationType, PosTileShape, UnitKind
from src.modules.audit_logs.models import AuditLog
from src.modules.catalog import service as catalog_service
from src.modules.catalog.models import (
    CatalogItem,
    CatalogItemOptionGroup,
    CatalogItemOptionValue,
    ProductVariant,
    ProductVariantOptionValue,
    VariantBarcode,
    VariantLocationSetting,
    VariantPosProfile,
    VariantUnit,
)
from src.modules.locations.models import Location
from src.modules.product_categories.models import ProductCategory
from src.modules.rbac.constants import ActionType
from src.modules.rbac.models import Permission
from src.modules.units.models import Unit
from src.storage.schemas import StoredObject

from tests.conftest import (
    auth_headers,
    make_tenant,
    make_user_with_permissions,
    permission,
    user_access_token,
)


async def test_catalog_item_create_builds_default_variant_unit_and_barcode(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="catalog-create")
    unit = await make_unit(db_session, code="cat-each", unit_kind=UnitKind.COUNT)
    category = await make_category(db_session, tenant_id=tenant.id, code="drinks")
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[
            permission("catalog", ActionType.CREATE),
            permission("catalog", ActionType.READ),
        ],
    )
    headers = auth_headers(user_access_token(actor))

    created = await client.post(
        "/api/v1/catalog-items",
        json={
            "name": "Coca-Cola",
            "local_name": "ကိုကာကိုလာ",
            "category_id": str(category.id),
            "variants": [
                {
                    "name": "330ml Can",
                    "base_unit_id": str(unit.id),
                    "default_sale_price": "1200.0000",
                    "default_purchase_cost": "1000.0000",
                    "barcode": "9550000330",
                }
            ],
        },
        headers=headers,
    )

    assert created.status_code == 201
    created_body = created.json()
    item_id = uuid.UUID(created_body["id"])
    assert created_body["code"].startswith("ITEM-")
    assert created_body["variants"][0]["sku"].startswith("VAR-")
    assert created_body["variants"][0]["barcodes"][0]["barcode"] == "9550000330"
    item = await db_session.scalar(select(CatalogItem).where(CatalogItem.id == item_id))
    variant = await db_session.scalar(
        select(ProductVariant).where(ProductVariant.catalog_item_id == item_id)
    )
    assert item is not None
    assert item.code.startswith("ITEM-")
    assert variant is not None
    assert variant.sku.startswith("VAR-")
    assert variant.default_sale_price == Decimal("1200.0000")

    base_unit = await db_session.scalar(
        select(VariantUnit).where(
            VariantUnit.product_variant_id == variant.id,
            VariantUnit.is_base_unit.is_(True),
        )
    )
    assert base_unit is not None
    assert base_unit.unit_id == unit.id
    assert base_unit.conversion_to_base == Decimal("1.00000000")

    barcode = await db_session.scalar(
        select(VariantBarcode).where(VariantBarcode.product_variant_id == variant.id)
    )
    assert barcode is not None
    assert barcode.barcode == "9550000330"
    assert barcode.variant_unit_id == base_unit.id
    assert barcode.is_primary is True

    listed = await client.get("/api/v1/product-variants?search=330", headers=headers)
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()["items"]] == [str(variant.id)]

    detail = await client.get(f"/api/v1/catalog-items/{item_id}/detail", headers=headers)
    assert detail.status_code == 200
    detail_variant = detail.json()["variants"][0]
    assert detail_variant["id"] == str(variant.id)
    assert detail_variant["variant_units"][0]["id"] == str(base_unit.id)
    assert detail_variant["barcodes"][0]["barcode"] == "9550000330"

    lookup = await client.get("/api/v1/catalog/barcode-lookup?barcode=9550000330", headers=headers)
    assert lookup.status_code == 200
    assert lookup.json()["catalog_item"]["id"] == str(item.id)
    assert lookup.json()["product_variant"]["id"] == str(variant.id)
    assert lookup.json()["variant_unit"]["id"] == str(base_unit.id)
    assert lookup.json()["barcode"]["id"] == str(barcode.id)

    actions = (
        (
            await db_session.execute(
                select(AuditLog.action).where(
                    AuditLog.tenant_id == tenant.id,
                    AuditLog.entity_id == item.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert actions == ["catalog.create_item"]

    child_actions = (
        await db_session.execute(
            select(AuditLog.entity_id, AuditLog.action).where(
                AuditLog.tenant_id == tenant.id,
                AuditLog.entity_id.in_([variant.id, base_unit.id, barcode.id]),
            )
        )
    ).all()
    assert dict(child_actions) == {
        variant.id: "catalog.create_variant",
        base_unit.id: "catalog.create_variant_unit",
        barcode.id: "catalog.create_variant_barcode",
    }


async def test_product_variant_auto_generates_sku_and_rejects_client_sku(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="catalog-sku")
    unit = await make_unit(db_session, code="cat-piece", unit_kind=UnitKind.COUNT)
    item = await make_item(db_session, tenant_id=tenant.id)
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("catalog", ActionType.CREATE)],
    )
    headers = auth_headers(user_access_token(actor))

    generated = await client.post(
        "/api/v1/product-variants",
        json={
            "catalog_item_id": str(item.id),
            "name": "Default",
            "base_unit_id": str(unit.id),
        },
        headers=headers,
    )
    manual_sku = await client.post(
        "/api/v1/product-variants",
        json={
            "catalog_item_id": str(item.id),
            "sku": "DUP-SKU",
            "name": "A",
            "base_unit_id": str(unit.id),
        },
        headers=headers,
    )

    assert generated.status_code == 201
    assert generated.json()["sku"].startswith("VAR-")
    assert manual_sku.status_code == 422


async def test_variant_units_allow_inactive_history_but_enforce_one_active_unit(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="catalog-unit-history")
    base_unit = await make_unit(db_session, code="cat-base-piece", unit_kind=UnitKind.COUNT)
    carton = await make_unit(db_session, code="cat-carton", unit_kind=UnitKind.PACKAGE)
    variant = await make_variant(db_session, tenant_id=tenant.id, base_unit_id=base_unit.id)
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[
            permission("catalog", ActionType.CREATE),
            permission("catalog", ActionType.READ),
            permission("catalog", ActionType.UPDATE),
            permission("catalog", ActionType.DELETE),
        ],
    )
    headers = auth_headers(user_access_token(actor))

    first = await client.post(
        "/api/v1/variant-units",
        json={
            "product_variant_id": str(variant.id),
            "unit_id": str(carton.id),
            "is_purchase_unit": True,
            "conversion_to_base": "24.00000000",
            "allow_decimal_quantity": False,
        },
        headers=headers,
    )
    fetched = await client.get(f"/api/v1/variant-units/{first.json()['id']}", headers=headers)
    updated = await client.patch(
        f"/api/v1/variant-units/{first.json()['id']}",
        json={"is_sales_unit": True, "rounding_precision": "1.00000000"},
        headers=headers,
    )
    duplicate_active = await client.post(
        "/api/v1/variant-units",
        json={
            "product_variant_id": str(variant.id),
            "unit_id": str(carton.id),
            "conversion_to_base": "30.00000000",
        },
        headers=headers,
    )
    deleted = await client.delete(f"/api/v1/variant-units/{first.json()['id']}", headers=headers)
    replacement = await client.post(
        "/api/v1/variant-units",
        json={
            "product_variant_id": str(variant.id),
            "unit_id": str(carton.id),
            "conversion_to_base": "30.00000000",
        },
        headers=headers,
    )

    assert first.status_code == 201
    assert fetched.status_code == 200
    assert fetched.json()["id"] == first.json()["id"]
    assert updated.status_code == 200
    assert updated.json()["is_sales_unit"] is True
    assert duplicate_active.status_code == 409
    assert duplicate_active.json()["error_code"] == "variant_unit_conflict"
    assert deleted.status_code == 204
    assert replacement.status_code == 201


async def test_variant_unit_requires_measured_quantity_round_trips(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="catalog-measured-flag")
    base_unit = await make_unit(db_session, code="cat-measured-piece", unit_kind=UnitKind.COUNT)
    bag_unit = await make_unit(db_session, code="cat-measured-bag", unit_kind=UnitKind.PACKAGE)
    variant = await make_variant(db_session, tenant_id=tenant.id, base_unit_id=base_unit.id)
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[
            permission("catalog", ActionType.CREATE),
            permission("catalog", ActionType.READ),
            permission("catalog", ActionType.UPDATE),
        ],
    )
    headers = auth_headers(user_access_token(actor))

    created = await client.post(
        "/api/v1/variant-units",
        json={
            "product_variant_id": str(variant.id),
            "unit_id": str(bag_unit.id),
            "is_purchase_unit": True,
            "conversion_to_base": "25.00000000",
            "requires_measured_quantity": True,
        },
        headers=headers,
    )
    assert created.status_code == 201
    variant_unit_id = created.json()["id"]
    assert created.json()["requires_measured_quantity"] is True

    fetched = await client.get(f"/api/v1/variant-units/{variant_unit_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["requires_measured_quantity"] is True

    updated = await client.patch(
        f"/api/v1/variant-units/{variant_unit_id}",
        json={"requires_measured_quantity": False},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["requires_measured_quantity"] is False

    audit_actions = (
        (
            await db_session.execute(
                select(AuditLog.action).where(
                    AuditLog.tenant_id == tenant.id,
                    AuditLog.entity_id == uuid.UUID(variant_unit_id),
                )
            )
        )
        .scalars()
        .all()
    )
    assert sorted(audit_actions) == [
        "catalog.create_variant_unit",
        "catalog.update_variant_unit",
    ]


async def test_referenced_variant_unit_is_immutable(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="catalog-immutable-unit")
    base_unit = await make_unit(db_session, code="immutable-piece", unit_kind=UnitKind.COUNT)
    carton = await make_unit(db_session, code="immutable-carton", unit_kind=UnitKind.PACKAGE)
    variant = await make_variant(db_session, tenant_id=tenant.id, base_unit_id=base_unit.id)
    variant_unit = VariantUnit(
        tenant_id=tenant.id,
        product_variant_id=variant.id,
        unit_id=carton.id,
        is_sales_unit=True,
        conversion_to_base=Decimal("12"),
    )
    db_session.add(variant_unit)
    await db_session.flush()
    db_session.add(
        VariantBarcode(
            tenant_id=tenant.id,
            product_variant_id=variant.id,
            variant_unit_id=variant_unit.id,
            barcode="immutable-unit-barcode",
        )
    )
    await db_session.commit()
    actor = await make_user_with_permissions(
        db_session, tenant=tenant, permissions=[permission("catalog", ActionType.UPDATE)]
    )

    response = await client.patch(
        f"/api/v1/variant-units/{variant_unit.id}",
        json={"conversion_to_base": "24"},
        headers=auth_headers(user_access_token(actor)),
    )

    assert response.status_code == 409
    assert response.json()["error_code"] == "variant_unit_immutable"


async def test_variant_unit_rejects_incompatible_non_package_measurement_kind(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="catalog-unit-kind")
    base_unit = await make_unit(db_session, code="kind-kg", unit_kind=UnitKind.WEIGHT)
    count_unit = await make_unit(db_session, code="kind-piece", unit_kind=UnitKind.COUNT)
    variant = await make_variant(db_session, tenant_id=tenant.id, base_unit_id=base_unit.id)
    actor = await make_user_with_permissions(
        db_session, tenant=tenant, permissions=[permission("catalog", ActionType.CREATE)]
    )

    response = await client.post(
        "/api/v1/variant-units",
        json={
            "product_variant_id": str(variant.id),
            "unit_id": str(count_unit.id),
            "is_sales_unit": True,
            "conversion_to_base": "1",
        },
        headers=auth_headers(user_access_token(actor)),
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "invalid_variant_unit_kind"


async def test_variant_barcode_can_target_specific_variant_unit(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="catalog-barcode")
    base_unit = await make_unit(db_session, code="cat-bottle", unit_kind=UnitKind.COUNT)
    carton = await make_unit(db_session, code="cat-barcode-carton", unit_kind=UnitKind.PACKAGE)
    variant = await make_variant(db_session, tenant_id=tenant.id, base_unit_id=base_unit.id)
    variant_unit = await make_variant_unit(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=variant.id,
        unit_id=carton.id,
        conversion_to_base=Decimal("24.00000000"),
    )
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[
            permission("catalog", ActionType.CREATE),
            permission("catalog", ActionType.READ),
            permission("catalog", ActionType.UPDATE),
            permission("catalog", ActionType.DELETE),
        ],
    )
    headers = auth_headers(user_access_token(actor))

    created = await client.post(
        "/api/v1/variant-barcodes",
        json={
            "product_variant_id": str(variant.id),
            "variant_unit_id": str(variant_unit.id),
            "barcode": "CARTON-BARCODE",
            "is_primary": True,
        },
        headers=headers,
    )
    fetched = await client.get(
        f"/api/v1/variant-barcodes/{created.json()['id']}",
        headers=headers,
    )
    updated = await client.patch(
        f"/api/v1/variant-barcodes/{created.json()['id']}",
        json={"barcode": "CARTON-BARCODE-UPDATED", "is_primary": False},
        headers=headers,
    )
    duplicate = await client.post(
        "/api/v1/variant-barcodes",
        json={
            "product_variant_id": str(variant.id),
            "barcode": "CARTON-BARCODE-UPDATED",
        },
        headers=headers,
    )
    deleted = await client.delete(
        f"/api/v1/variant-barcodes/{created.json()['id']}",
        headers=headers,
    )

    assert created.status_code == 201
    assert created.json()["variant_unit_id"] == str(variant_unit.id)
    assert fetched.status_code == 200
    assert fetched.json()["barcode"] == "CARTON-BARCODE"
    assert updated.status_code == 200
    assert updated.json()["barcode"] == "CARTON-BARCODE-UPDATED"
    assert duplicate.status_code == 409
    assert duplicate.json()["error_code"] == "variant_barcode_conflict"
    assert deleted.status_code == 204


async def test_variant_pos_profile_lifecycle(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="catalog-pos-profile")
    other_tenant = await make_tenant(db_session, code="catalog-pos-profile-other")
    unit = await make_unit(db_session, code="cat-pos-piece", unit_kind=UnitKind.COUNT)
    variant = await make_variant(db_session, tenant_id=tenant.id, base_unit_id=unit.id)
    second_variant = await make_variant(
        db_session,
        tenant_id=tenant.id,
        base_unit_id=unit.id,
        sku="SECOND-POS",
    )
    second_profile = VariantPosProfile(
        tenant_id=tenant.id,
        product_variant_id=second_variant.id,
        label="Second",
    )
    other_variant = await make_variant(
        db_session,
        tenant_id=other_tenant.id,
        base_unit_id=unit.id,
        sku="OTHER-POS",
    )
    other_profile = VariantPosProfile(
        tenant_id=other_tenant.id,
        product_variant_id=other_variant.id,
        label="Other",
    )
    db_session.add_all([second_profile, other_profile])
    await db_session.flush()
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[
            permission("catalog", ActionType.CREATE),
            permission("catalog", ActionType.READ),
            permission("catalog", ActionType.UPDATE),
            permission("catalog", ActionType.DELETE),
        ],
    )
    read_only = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("catalog", ActionType.READ)],
    )
    headers = auth_headers(user_access_token(actor))

    denied = await client.post(
        "/api/v1/variant-pos-profiles",
        json={"product_variant_id": str(variant.id), "label": "Denied"},
        headers=auth_headers(user_access_token(read_only)),
    )
    created = await client.post(
        "/api/v1/variant-pos-profiles",
        json={
            "product_variant_id": str(variant.id),
            "label": "Front Tile",
            "color": "#22c55e",
            "shape": "hexagon",
            "sort_order": 10,
        },
        headers=headers,
    )
    profile_id = created.json()["id"] if created.status_code == 201 else str(uuid.uuid4())
    duplicate = await client.post(
        "/api/v1/variant-pos-profiles",
        json={"product_variant_id": str(variant.id), "label": "Duplicate"},
        headers=headers,
    )
    listed = await client.get(
        f"/api/v1/variant-pos-profiles?product_variant_id={variant.id}",
        headers=headers,
    )
    fetched = await client.get(f"/api/v1/variant-pos-profiles/{profile_id}", headers=headers)
    updated = await client.patch(
        f"/api/v1/variant-pos-profiles/{profile_id}",
        json={"label": "Checkout Tile", "shape": "circle", "is_visible": False},
        headers=headers,
    )
    conflicting_update = await client.patch(
        f"/api/v1/variant-pos-profiles/{profile_id}",
        json={"product_variant_id": str(second_variant.id)},
        headers=headers,
    )
    not_found = await client.get(
        f"/api/v1/variant-pos-profiles/{other_profile.id}",
        headers=headers,
    )
    deleted = await client.delete(f"/api/v1/variant-pos-profiles/{profile_id}", headers=headers)

    assert denied.status_code == 403
    assert created.status_code == 201
    assert created.json()["shape"] == PosTileShape.HEXAGON.value
    assert duplicate.status_code == 409
    assert duplicate.json()["error_code"] == "variant_pos_profile_conflict"
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()["items"]] == [profile_id]
    assert fetched.status_code == 200
    assert fetched.json()["label"] == "Front Tile"
    assert updated.status_code == 200
    assert updated.json()["label"] == "Checkout Tile"
    assert updated.json()["is_visible"] is False
    assert conflicting_update.status_code == 409
    assert conflicting_update.json()["error_code"] == "variant_pos_profile_conflict"
    assert not_found.status_code == 404
    assert deleted.status_code == 204
    assert (
        await db_session.scalar(
            select(VariantPosProfile).where(VariantPosProfile.id == uuid.UUID(profile_id))
        )
        is None
    )


async def test_catalog_item_image_upload_and_delete_lifecycle(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant = await make_tenant(db_session, code="catalog-item-image")
    item = await make_item(db_session, tenant_id=tenant.id, name="Image Item")
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[
            permission("catalog", ActionType.READ),
            permission("catalog", ActionType.UPDATE),
        ],
    )
    read_only = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("catalog", ActionType.READ)],
    )
    headers = auth_headers(user_access_token(actor))

    uploaded_keys: list[str] = []
    deleted_keys: list[str | None] = []

    async def fake_upload_bytes(data: bytes, *, key: str, content_type: str) -> StoredObject:
        uploaded_keys.append(key)
        return StoredObject(key=key)

    async def fake_delete_if_replaced(old_key: str | None, new_key: str | None) -> None:
        if old_key is not None and old_key != new_key:
            deleted_keys.append(old_key)

    async def fake_delete_best_effort(key: str | None) -> None:
        deleted_keys.append(key)

    # Patch the S3 network call only, keeping upload_image's real content-type/size validation.
    monkeypatch.setattr(catalog_service.storage_service, "_upload_bytes", fake_upload_bytes)
    monkeypatch.setattr(
        catalog_service.storage_service, "delete_if_replaced", fake_delete_if_replaced
    )
    monkeypatch.setattr(
        catalog_service.storage_service, "delete_best_effort", fake_delete_best_effort
    )

    denied = await client.put(
        f"/api/v1/catalog-items/{item.id}/image",
        files={"image": ("photo.jpg", b"fake-jpeg-bytes", "image/jpeg")},
        headers=auth_headers(user_access_token(read_only)),
    )
    uploaded = await client.put(
        f"/api/v1/catalog-items/{item.id}/image",
        files={"image": ("photo.jpg", b"fake-jpeg-bytes", "image/jpeg")},
        headers=headers,
    )
    replaced = await client.put(
        f"/api/v1/catalog-items/{item.id}/image",
        files={"image": ("photo-2.jpg", b"more-fake-bytes", "image/jpeg")},
        headers=headers,
    )
    unsupported = await client.put(
        f"/api/v1/catalog-items/{item.id}/image",
        files={"image": ("photo.txt", b"not-an-image", "text/plain")},
        headers=headers,
    )
    not_found = await client.put(
        f"/api/v1/catalog-items/{uuid.uuid4()}/image",
        files={"image": ("photo.jpg", b"fake-jpeg-bytes", "image/jpeg")},
        headers=headers,
    )
    deleted = await client.delete(f"/api/v1/catalog-items/{item.id}/image", headers=headers)

    assert denied.status_code == 403
    assert uploaded.status_code == 200
    assert uploaded.json()["image_url"] == f"https://cdn.test/{uploaded_keys[0]}"
    assert replaced.status_code == 200
    assert replaced.json()["image_url"] == f"https://cdn.test/{uploaded_keys[1]}"
    assert unsupported.status_code == 415
    assert unsupported.json()["error_code"] == "unsupported_file_type"
    assert not_found.status_code == 404
    assert deleted.status_code == 200
    assert deleted.json()["image_url"] is None
    assert deleted_keys == [uploaded_keys[0], uploaded_keys[1]]

    await db_session.refresh(item)
    assert item.image_key is None


async def test_variant_location_settings_store_low_stock_per_location(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="catalog-location")
    unit = await make_unit(db_session, code="cat-location-piece", unit_kind=UnitKind.COUNT)
    variant = await make_variant(db_session, tenant_id=tenant.id, base_unit_id=unit.id)
    second_variant = await make_variant(
        db_session,
        tenant_id=tenant.id,
        base_unit_id=unit.id,
        sku="SECOND-LOCATION",
    )
    store = await make_location(db_session, tenant_id=tenant.id, code="store")
    second_setting = VariantLocationSetting(
        tenant_id=tenant.id,
        product_variant_id=second_variant.id,
        location_id=store.id,
    )
    db_session.add(second_setting)
    await db_session.flush()
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[
            permission("catalog", ActionType.CREATE),
            permission("catalog", ActionType.READ),
            permission("catalog", ActionType.UPDATE),
            permission("catalog", ActionType.DELETE),
        ],
    )
    headers = auth_headers(user_access_token(actor))

    created = await client.post(
        "/api/v1/variant-location-settings",
        json={
            "product_variant_id": str(variant.id),
            "location_id": str(store.id),
            "low_stock_quantity_base": "5.00000000",
        },
        headers=headers,
    )
    listed = await client.get(
        f"/api/v1/variant-location-settings?product_variant_id={variant.id}",
        headers=headers,
    )
    fetched = await client.get(
        f"/api/v1/variant-location-settings/{created.json()['id']}",
        headers=headers,
    )
    updated = await client.patch(
        f"/api/v1/variant-location-settings/{created.json()['id']}",
        json={"is_available": False, "low_stock_quantity_base": "7.00000000"},
        headers=headers,
    )
    duplicate = await client.post(
        "/api/v1/variant-location-settings",
        json={
            "product_variant_id": str(variant.id),
            "location_id": str(store.id),
        },
        headers=headers,
    )
    conflicting_update = await client.patch(
        f"/api/v1/variant-location-settings/{created.json()['id']}",
        json={"product_variant_id": str(second_variant.id)},
        headers=headers,
    )
    deleted = await client.delete(
        f"/api/v1/variant-location-settings/{created.json()['id']}",
        headers=headers,
    )

    assert created.status_code == 201
    assert created.json()["low_stock_quantity_base"] == "5.00000000"
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()["items"]] == [created.json()["id"]]
    assert fetched.status_code == 200
    assert fetched.json()["location_id"] == str(store.id)
    assert updated.status_code == 200
    assert updated.json()["is_available"] is False
    assert updated.json()["low_stock_quantity_base"] == "7.00000000"
    assert duplicate.status_code == 409
    assert duplicate.json()["error_code"] == "variant_location_setting_conflict"
    assert conflicting_update.status_code == 409
    assert conflicting_update.json()["error_code"] == "variant_location_setting_conflict"
    assert deleted.status_code == 204

    setting = await db_session.scalar(
        select(VariantLocationSetting).where(
            VariantLocationSetting.id == uuid.UUID(created.json()["id"])
        )
    )
    assert setting is None


async def test_catalog_item_option_group_value_and_variant_link_lifecycle(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="catalog-options")
    other_tenant = await make_tenant(db_session, code="catalog-options-other")
    unit = await make_unit(db_session, code="cat-option-piece", unit_kind=UnitKind.COUNT)
    item = await make_item(db_session, tenant_id=tenant.id, name="Optioned Item")
    variant = ProductVariant(
        tenant_id=tenant.id,
        catalog_item_id=item.id,
        sku="OPTION-SKU",
        name="Optioned Variant",
        base_unit_id=unit.id,
    )
    other_item = await make_item(db_session, tenant_id=tenant.id, name="Other Optioned Item")
    other_variant = ProductVariant(
        tenant_id=tenant.id,
        catalog_item_id=other_item.id,
        sku="OPTION-OTHER-SKU",
        name="Other Optioned Variant",
        base_unit_id=unit.id,
    )
    other_tenant_item = await make_item(db_session, tenant_id=other_tenant.id, name="Other Tenant")
    other_tenant_group = CatalogItemOptionGroup(
        tenant_id=other_tenant.id,
        catalog_item_id=other_tenant_item.id,
        name="Size",
    )
    db_session.add_all([variant, other_variant, other_tenant_group])
    await db_session.flush()
    other_tenant_value = CatalogItemOptionValue(
        tenant_id=other_tenant.id,
        option_group_id=other_tenant_group.id,
        value="Small",
    )
    db_session.add(other_tenant_value)
    await db_session.flush()
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[
            permission("catalog", ActionType.CREATE),
            permission("catalog", ActionType.READ),
            permission("catalog", ActionType.UPDATE),
            permission("catalog", ActionType.DELETE),
        ],
    )
    read_only = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("catalog", ActionType.READ)],
    )
    headers = auth_headers(user_access_token(actor))

    denied = await client.post(
        "/api/v1/catalog-item-option-groups",
        json={"catalog_item_id": str(item.id), "name": "Denied"},
        headers=auth_headers(user_access_token(read_only)),
    )
    assert denied.status_code == 403

    created_group = await client.post(
        "/api/v1/catalog-item-option-groups",
        json={"catalog_item_id": str(item.id), "name": "Size", "position": 10},
        headers=headers,
    )
    assert created_group.status_code == 201
    group_id = created_group.json()["id"]

    duplicate_group = await client.post(
        "/api/v1/catalog-item-option-groups",
        json={"catalog_item_id": str(item.id), "name": "Size"},
        headers=headers,
    )
    assert duplicate_group.status_code == 409
    assert duplicate_group.json()["error_code"] == "catalog_item_option_group_conflict"

    not_found = await client.get(
        f"/api/v1/catalog-item-option-groups/{other_tenant_group.id}",
        headers=headers,
    )
    assert not_found.status_code == 404

    listed_groups = await client.get(
        f"/api/v1/catalog-item-option-groups?catalog_item_id={item.id}&search=siz",
        headers=headers,
    )
    assert listed_groups.status_code == 200
    assert [row["id"] for row in listed_groups.json()["items"]] == [group_id]

    small = await client.post(
        "/api/v1/catalog-item-option-values",
        json={"option_group_id": group_id, "value": "Small", "position": 1},
        headers=headers,
    )
    medium = await client.post(
        "/api/v1/catalog-item-option-values",
        json={"option_group_id": group_id, "value": "Medium", "position": 2},
        headers=headers,
    )
    assert small.status_code == 201
    assert medium.status_code == 201
    small_value_id = small.json()["id"]
    medium_value_id = medium.json()["id"]

    duplicate_value = await client.post(
        "/api/v1/catalog-item-option-values",
        json={"option_group_id": group_id, "value": "Small"},
        headers=headers,
    )
    assert duplicate_value.status_code == 409
    assert duplicate_value.json()["error_code"] == "catalog_item_option_value_conflict"

    group_detail = await client.get(
        f"/api/v1/catalog-item-option-groups/{group_id}/detail",
        headers=headers,
    )
    assert group_detail.status_code == 200
    assert [value["value"] for value in group_detail.json()["values"]] == ["Small", "Medium"]

    updated_group = await client.patch(
        f"/api/v1/catalog-item-option-groups/{group_id}",
        json={"name": "Pack Size", "position": 20},
        headers=headers,
    )
    updated_value = await client.patch(
        f"/api/v1/catalog-item-option-values/{small_value_id}",
        json={"value": "Small Pack", "position": 11},
        headers=headers,
    )
    assert updated_group.status_code == 200
    assert updated_group.json()["name"] == "Pack Size"
    assert updated_value.status_code == 200
    assert updated_value.json()["value"] == "Small Pack"

    link = await client.post(
        "/api/v1/product-variant-option-values",
        json={"product_variant_id": str(variant.id), "option_value_id": small_value_id},
        headers=headers,
    )
    assert link.status_code == 201
    link_id = link.json()["id"]

    duplicate_link = await client.post(
        "/api/v1/product-variant-option-values",
        json={"product_variant_id": str(variant.id), "option_value_id": small_value_id},
        headers=headers,
    )
    same_group_link = await client.post(
        "/api/v1/product-variant-option-values",
        json={"product_variant_id": str(variant.id), "option_value_id": medium_value_id},
        headers=headers,
    )
    cross_item_link = await client.post(
        "/api/v1/product-variant-option-values",
        json={"product_variant_id": str(other_variant.id), "option_value_id": small_value_id},
        headers=headers,
    )
    cross_tenant_link = await client.post(
        "/api/v1/product-variant-option-values",
        json={
            "product_variant_id": str(variant.id),
            "option_value_id": str(other_tenant_value.id),
        },
        headers=headers,
    )

    assert duplicate_link.status_code == 409
    assert duplicate_link.json()["error_code"] == "product_variant_option_value_conflict"
    assert same_group_link.status_code == 409
    assert same_group_link.json()["error_code"] == "product_variant_option_group_conflict"
    assert cross_item_link.status_code == 400
    assert cross_item_link.json()["error_code"] == "invalid_product_variant_option_value"
    assert cross_tenant_link.status_code == 400
    assert cross_tenant_link.json()["error_code"] == "invalid_catalog_item_option_value"

    listed_links = await client.get(
        f"/api/v1/product-variant-option-values?product_variant_id={variant.id}",
        headers=headers,
    )
    fetched_link = await client.get(
        f"/api/v1/product-variant-option-values/{link_id}",
        headers=headers,
    )
    assert listed_links.status_code == 200
    assert [row["id"] for row in listed_links.json()["items"]] == [link_id]
    assert fetched_link.status_code == 200
    assert fetched_link.json()["option_value_id"] == small_value_id

    item_detail = await client.get(f"/api/v1/catalog-items/{item.id}/detail", headers=headers)
    assert item_detail.status_code == 200
    detail_body = item_detail.json()
    detail_values = [
        value["value"] for group in detail_body["option_groups"] for value in group["values"]
    ]
    detail_links = [
        link["id"]
        for variant_body in detail_body["variants"]
        for link in variant_body["option_values"]
    ]
    assert "Small Pack" in detail_values
    assert link_id in detail_links

    deleted_link = await client.delete(
        f"/api/v1/product-variant-option-values/{link_id}",
        headers=headers,
    )
    deleted_value = await client.delete(
        f"/api/v1/catalog-item-option-values/{medium_value_id}",
        headers=headers,
    )
    deleted_group = await client.delete(
        f"/api/v1/catalog-item-option-groups/{group_id}",
        headers=headers,
    )
    assert deleted_link.status_code == 204
    assert deleted_value.status_code == 204
    assert deleted_group.status_code == 204

    assert (
        await db_session.scalar(
            select(ProductVariantOptionValue).where(
                ProductVariantOptionValue.id == uuid.UUID(link_id)
            )
        )
        is None
    )
    assert (
        await db_session.scalar(
            select(CatalogItemOptionGroup).where(CatalogItemOptionGroup.id == uuid.UUID(group_id))
        )
        is None
    )

    actions = {
        action
        for (action,) in (
            await db_session.execute(select(AuditLog.action).where(AuditLog.tenant_id == tenant.id))
        ).all()
    }
    assert {
        "catalog.create_option_group",
        "catalog.update_option_group",
        "catalog.delete_option_group",
        "catalog.create_option_value",
        "catalog.update_option_value",
        "catalog.delete_option_value",
        "catalog.create_variant_option_value",
        "catalog.delete_variant_option_value",
    }.issubset(actions)


async def test_seed_adds_catalog_permissions(db_session: AsyncSession) -> None:
    await _ensure_permissions(db_session)
    await _ensure_permissions(db_session)

    rows = await db_session.execute(
        select(Permission.code).where(Permission.module == "catalog").order_by(Permission.code)
    )

    assert {code for (code,) in rows.all()} == {
        "catalog.create",
        "catalog.delete",
        "catalog.read",
        "catalog.update",
    }


async def make_unit(
    db_session: AsyncSession,
    *,
    code: str,
    unit_kind: UnitKind,
    is_active: bool = True,
) -> Unit:
    unit = Unit(
        code=code,
        name_en=code.title(),
        unit_kind=unit_kind,
        is_active=is_active,
    )
    db_session.add(unit)
    await db_session.flush()
    return unit


async def make_category(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    code: str,
) -> ProductCategory:
    category = ProductCategory(tenant_id=tenant_id, code=code, name=code.title())
    db_session.add(category)
    await db_session.flush()
    return category


async def make_item(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    name: str = "Catalog Item",
    code: str | None = None,
) -> CatalogItem:
    item = CatalogItem(tenant_id=tenant_id, code=code or f"ITEM-{uuid.uuid4().hex[:8]}", name=name)
    db_session.add(item)
    await db_session.flush()
    return item


async def make_variant(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    base_unit_id: uuid.UUID,
    sku: str | None = None,
) -> ProductVariant:
    item = await make_item(db_session, tenant_id=tenant_id, name=sku or "Variant Item")
    variant = ProductVariant(
        tenant_id=tenant_id,
        catalog_item_id=item.id,
        sku=sku or f"VAR-{uuid.uuid4().hex[:8]}",
        name="Default",
        base_unit_id=base_unit_id,
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
    conversion_to_base: Decimal,
) -> VariantUnit:
    variant_unit = VariantUnit(
        tenant_id=tenant_id,
        product_variant_id=product_variant_id,
        unit_id=unit_id,
        conversion_to_base=conversion_to_base,
    )
    db_session.add(variant_unit)
    await db_session.flush()
    return variant_unit


async def make_location(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    code: str,
) -> Location:
    location = Location(
        tenant_id=tenant_id,
        code=code,
        name=code.title(),
        location_type=LocationType.STORE,
        is_sellable=True,
    )
    db_session.add(location)
    await db_session.flush()
    return location
