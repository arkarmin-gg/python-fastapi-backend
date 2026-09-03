import uuid
from decimal import Decimal
from typing import Any

from fastapi import UploadFile
from sqlalchemy import Select, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.foundation_enums import PartyStatus, UnitKind
from src.modules.audit_logs.service import record_audit_log
from src.modules.catalog.exceptions import (
    CatalogItemNotFound,
    CatalogItemOptionGroupConflict,
    CatalogItemOptionGroupNotFound,
    CatalogItemOptionValueConflict,
    CatalogItemOptionValueNotFound,
    InvalidCatalogCategory,
    InvalidCatalogItem,
    InvalidCatalogItemOptionGroup,
    InvalidCatalogItemOptionValue,
    InvalidCatalogLocation,
    InvalidCatalogSupplier,
    InvalidCatalogUnit,
    InvalidProductVariantOptionValue,
    InvalidVariantBaseUnit,
    InvalidVariantUnit,
    InvalidVariantUnitKind,
    ProductVariantNotFound,
    ProductVariantOptionGroupConflict,
    ProductVariantOptionValueConflict,
    ProductVariantOptionValueNotFound,
    ProductVariantSkuConflict,
    VariantBarcodeConflict,
    VariantBarcodeNotFound,
    VariantLocationSettingConflict,
    VariantLocationSettingNotFound,
    VariantPosProfileConflict,
    VariantPosProfileNotFound,
    VariantPrimaryBarcodeConflict,
    VariantUnitBaseConflict,
    VariantUnitConflict,
    VariantUnitImmutable,
    VariantUnitNotFound,
)
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
from src.modules.catalog.schemas import (
    CatalogItemCreate,
    CatalogItemFilters,
    CatalogItemOptionGroupCreate,
    CatalogItemOptionGroupFilters,
    CatalogItemOptionGroupUpdate,
    CatalogItemOptionValueCreate,
    CatalogItemOptionValueFilters,
    CatalogItemOptionValueUpdate,
    CatalogItemUpdate,
    CatalogItemVariantCreate,
    ProductVariantCreate,
    ProductVariantFilters,
    ProductVariantOptionValueCreate,
    ProductVariantOptionValueFilters,
    ProductVariantOptionValueUpdate,
    ProductVariantUpdate,
    VariantBarcodeCreate,
    VariantBarcodeFilters,
    VariantBarcodeUpdate,
    VariantLocationSettingCreate,
    VariantLocationSettingFilters,
    VariantLocationSettingUpdate,
    VariantPosProfileCreate,
    VariantPosProfileFilters,
    VariantPosProfileInput,
    VariantPosProfileUpdate,
    VariantUnitCreate,
    VariantUnitFilters,
    VariantUnitUpdate,
)
from src.modules.codes.service import generate_code
from src.modules.locations.models import Location
from src.modules.price_rules.models import PriceRule
from src.modules.product_categories.models import ProductCategory
from src.modules.purchase_invoices.models import PurchaseInvoiceLine
from src.modules.repack_orders.models import RepackOrderInput, RepackOrderOutput
from src.modules.sales_invoices.models import SalesInvoiceLine
from src.modules.stock_adjustments.models import StockAdjustmentLine
from src.modules.stock_transfers.models import StockTransferLine
from src.modules.suppliers.models import Supplier
from src.modules.units.models import Unit
from src.pagination import Page, PaginationParams, paginate
from src.query_filters import SortSpec, apply_sort, search_clause
from src.storage import service as storage_service

BASE_CONVERSION = Decimal("1")

CATALOG_ITEM_SORT_COLUMNS = {
    "code": CatalogItem.code,
    "name": CatalogItem.name,
    "item_kind": CatalogItem.item_kind,
    "created_at": CatalogItem.created_at,
    "id": CatalogItem.id,
}
PRODUCT_VARIANT_SORT_COLUMNS = {
    "sku": ProductVariant.sku,
    "name": ProductVariant.name,
    "created_at": ProductVariant.created_at,
    "id": ProductVariant.id,
}
VARIANT_UNIT_SORT_COLUMNS = {
    "product_variant_id": VariantUnit.product_variant_id,
    "unit_id": VariantUnit.unit_id,
    "conversion_to_base": VariantUnit.conversion_to_base,
    "id": VariantUnit.id,
}
VARIANT_BARCODE_SORT_COLUMNS = {
    "barcode": VariantBarcode.barcode,
    "product_variant_id": VariantBarcode.product_variant_id,
    "id": VariantBarcode.id,
}
VARIANT_POS_PROFILE_SORT_COLUMNS = {
    "sort_order": VariantPosProfile.sort_order,
    "product_variant_id": VariantPosProfile.product_variant_id,
    "id": VariantPosProfile.id,
}
VARIANT_LOCATION_SETTING_SORT_COLUMNS = {
    "product_variant_id": VariantLocationSetting.product_variant_id,
    "location_id": VariantLocationSetting.location_id,
    "id": VariantLocationSetting.id,
}
OPTION_GROUP_SORT_COLUMNS = {
    "catalog_item_id": CatalogItemOptionGroup.catalog_item_id,
    "name": CatalogItemOptionGroup.name,
    "position": CatalogItemOptionGroup.position,
    "id": CatalogItemOptionGroup.id,
}
OPTION_VALUE_SORT_COLUMNS = {
    "option_group_id": CatalogItemOptionValue.option_group_id,
    "value": CatalogItemOptionValue.value,
    "position": CatalogItemOptionValue.position,
    "id": CatalogItemOptionValue.id,
}
VARIANT_OPTION_VALUE_SORT_COLUMNS = {
    "product_variant_id": ProductVariantOptionValue.product_variant_id,
    "option_value_id": ProductVariantOptionValue.option_value_id,
    "id": ProductVariantOptionValue.id,
}


async def get_catalog_item_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    catalog_item_id: uuid.UUID,
) -> CatalogItem | None:
    return await db.scalar(
        select(CatalogItem).where(
            CatalogItem.tenant_id == tenant_id,
            CatalogItem.id == catalog_item_id,
        )
    )


async def get_catalog_item_detail_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    catalog_item_id: uuid.UUID,
) -> CatalogItem | None:
    return await db.scalar(
        select(CatalogItem)
        .options(
            selectinload(CatalogItem.variants).selectinload(ProductVariant.variant_units),
            selectinload(CatalogItem.variants).selectinload(ProductVariant.barcodes),
            selectinload(CatalogItem.variants).selectinload(ProductVariant.pos_profile),
            selectinload(CatalogItem.variants).selectinload(ProductVariant.location_settings),
            selectinload(CatalogItem.variants).selectinload(ProductVariant.option_values),
            selectinload(CatalogItem.option_groups).selectinload(CatalogItemOptionGroup.values),
        )
        .where(
            CatalogItem.tenant_id == tenant_id,
            CatalogItem.id == catalog_item_id,
        )
    )


async def lookup_barcode(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    barcode_value: str,
) -> dict[str, Any]:
    barcode = await db.scalar(
        select(VariantBarcode)
        .options(
            selectinload(VariantBarcode.product_variant).selectinload(ProductVariant.catalog_item),
            selectinload(VariantBarcode.variant_unit),
        )
        .join(ProductVariant, ProductVariant.id == VariantBarcode.product_variant_id)
        .join(CatalogItem, CatalogItem.id == ProductVariant.catalog_item_id)
        .where(
            VariantBarcode.tenant_id == tenant_id,
            VariantBarcode.barcode == barcode_value,
            VariantBarcode.is_active.is_(True),
            ProductVariant.is_active.is_(True),
            CatalogItem.is_active.is_(True),
        )
    )
    if barcode is None:
        raise VariantBarcodeNotFound()
    return {
        "catalog_item": barcode.product_variant.catalog_item,
        "product_variant": barcode.product_variant,
        "variant_unit": barcode.variant_unit,
        "barcode": barcode,
    }


async def list_catalog_items(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: CatalogItemFilters,
    sort: tuple[SortSpec, ...],
) -> Page[CatalogItem]:
    stmt = _apply_catalog_item_filters(
        select(CatalogItem).where(CatalogItem.tenant_id == tenant_id),
        filters,
    )
    stmt = apply_sort(stmt, sort, CATALOG_ITEM_SORT_COLUMNS)
    count_stmt = _apply_catalog_item_filters(
        select(func.count(CatalogItem.id)).where(CatalogItem.tenant_id == tenant_id),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def create_catalog_item(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: CatalogItemCreate,
    *,
    actor_user_id: uuid.UUID,
) -> CatalogItem:
    if data.category_id is not None:
        await _ensure_active_category(db, tenant_id, data.category_id)
    fields = data.model_dump(exclude={"variants", "pos_profile"})
    item = CatalogItem(
        tenant_id=tenant_id,
        code=await generate_code(db, tenant_id, "catalog_item"),
        **fields,
    )
    db.add(item)
    await db.flush()
    for variant_input in data.variants:
        await _create_catalog_item_variant(
            db,
            tenant_id,
            item.id,
            variant_input,
            default_pos_profile=data.pos_profile,
            actor_user_id=actor_user_id,
        )
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="catalog.create_item",
        entity_type="catalog_item",
        entity_id=item.id,
        after_json=_loggable_catalog_item(item),
    )
    await db.commit()
    detail = await get_catalog_item_detail_by_id(db, tenant_id, item.id)
    assert detail is not None
    return detail


async def _create_catalog_item_variant(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    catalog_item_id: uuid.UUID,
    data: CatalogItemVariantCreate,
    *,
    default_pos_profile: VariantPosProfileInput | None,
    actor_user_id: uuid.UUID,
) -> ProductVariant:
    await _ensure_active_catalog_item(db, tenant_id, catalog_item_id)
    await _ensure_active_unit(db, data.base_unit_id)

    sku = await generate_code(db, tenant_id, "product_variant")
    await _ensure_sku_available(db, tenant_id, sku)

    variant = ProductVariant(
        tenant_id=tenant_id,
        catalog_item_id=catalog_item_id,
        sku=sku,
        name=data.name,
        local_name=data.local_name,
        base_unit_id=data.base_unit_id,
        default_sale_price=data.default_sale_price,
        default_purchase_cost=data.default_purchase_cost,
        track_inventory=data.track_inventory,
        track_batches=data.track_batches,
        track_expiry=data.track_expiry,
    )
    db.add(variant)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="catalog.create_variant",
        entity_type="product_variant",
        entity_id=variant.id,
        after_json=_loggable_product_variant(variant),
    )

    base_unit = VariantUnit(
        tenant_id=tenant_id,
        product_variant_id=variant.id,
        unit_id=variant.base_unit_id,
        is_base_unit=True,
        is_purchase_unit=True,
        is_sales_unit=True,
        conversion_to_base=BASE_CONVERSION,
        allow_decimal_quantity=True,
    )
    db.add(base_unit)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="catalog.create_variant_unit",
        entity_type="variant_unit",
        entity_id=base_unit.id,
        after_json=_loggable_variant_unit(base_unit),
    )

    if data.barcode is not None:
        await _ensure_barcode_available(db, tenant_id, data.barcode)
        barcode = VariantBarcode(
            tenant_id=tenant_id,
            product_variant_id=variant.id,
            variant_unit_id=base_unit.id,
            barcode=data.barcode,
            is_primary=True,
        )
        db.add(barcode)
        await db.flush()
        await record_audit_log(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="catalog.create_variant_barcode",
            entity_type="variant_barcode",
            entity_id=barcode.id,
            after_json=_loggable_variant_barcode(barcode),
        )

    profile_input = data.pos_profile or default_pos_profile
    if profile_input is not None:
        profile = VariantPosProfile(
            tenant_id=tenant_id,
            product_variant_id=variant.id,
            **profile_input.model_dump(),
        )
        db.add(profile)
        await db.flush()
        await record_audit_log(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="catalog.create_variant_pos_profile",
            entity_type="variant_pos_profile",
            entity_id=profile.id,
            after_json=_loggable_variant_pos_profile(profile),
        )

    for location_setting in data.location_settings:
        await _ensure_active_location(db, tenant_id, location_setting.location_id)
        if location_setting.preferred_supplier_id is not None:
            await _ensure_active_supplier(db, tenant_id, location_setting.preferred_supplier_id)
        setting = VariantLocationSetting(
            tenant_id=tenant_id,
            product_variant_id=variant.id,
            **location_setting.model_dump(),
        )
        db.add(setting)
        await db.flush()
        await record_audit_log(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="catalog.create_variant_location_setting",
            entity_type="variant_location_setting",
            entity_id=setting.id,
            after_json=_loggable_variant_location_setting(setting),
        )

    return variant


async def update_catalog_item(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    catalog_item_id: uuid.UUID,
    data: CatalogItemUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> CatalogItem:
    item = await get_catalog_item_by_id(db, tenant_id, catalog_item_id)
    if item is None:
        raise CatalogItemNotFound()
    before = _loggable_catalog_item(item)
    fields = data.model_dump(exclude_unset=True)
    if "category_id" in fields and fields["category_id"] is not None:
        await _ensure_active_category(db, tenant_id, fields["category_id"])
    for key, value in fields.items():
        setattr(item, key, value)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="catalog.update_item",
        entity_type="catalog_item",
        entity_id=item.id,
        before_json=before,
        after_json=_loggable_catalog_item(item),
    )
    await db.commit()
    await db.refresh(item)
    return item


async def deactivate_catalog_item(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    catalog_item_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    item = await get_catalog_item_by_id(db, tenant_id, catalog_item_id)
    if item is None:
        raise CatalogItemNotFound()
    before = _loggable_catalog_item(item)
    item.is_active = False
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="catalog.deactivate_item",
        entity_type="catalog_item",
        entity_id=item.id,
        before_json=before,
        after_json=_loggable_catalog_item(item),
    )
    await db.commit()


async def upload_catalog_item_image(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    catalog_item_id: uuid.UUID,
    file: UploadFile,
    *,
    actor_user_id: uuid.UUID,
) -> CatalogItem:
    item = await get_catalog_item_by_id(db, tenant_id, catalog_item_id)
    if item is None:
        raise CatalogItemNotFound()
    before = _loggable_catalog_item(item)
    old_key = item.image_key
    stored = await storage_service.upload_image(file, prefix=f"catalog-items/{tenant_id}")
    item.image_key = stored.key
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="catalog.update_item_image",
        entity_type="catalog_item",
        entity_id=item.id,
        before_json=before,
        after_json=_loggable_catalog_item(item),
    )
    await db.commit()
    await db.refresh(item)
    await storage_service.delete_if_replaced(old_key, item.image_key)
    return item


async def delete_catalog_item_image(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    catalog_item_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> CatalogItem:
    item = await get_catalog_item_by_id(db, tenant_id, catalog_item_id)
    if item is None:
        raise CatalogItemNotFound()
    old_key = item.image_key
    if old_key is None:
        return item
    before = _loggable_catalog_item(item)
    item.image_key = None
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="catalog.remove_item_image",
        entity_type="catalog_item",
        entity_id=item.id,
        before_json=before,
        after_json=_loggable_catalog_item(item),
    )
    await db.commit()
    await db.refresh(item)
    await storage_service.delete_best_effort(old_key)
    return item


async def get_product_variant_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
) -> ProductVariant | None:
    return await db.scalar(
        select(ProductVariant).where(
            ProductVariant.tenant_id == tenant_id,
            ProductVariant.id == product_variant_id,
        )
    )


async def list_product_variants(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: ProductVariantFilters,
    sort: tuple[SortSpec, ...],
) -> Page[ProductVariant]:
    stmt = _apply_product_variant_filters(
        select(ProductVariant).where(ProductVariant.tenant_id == tenant_id),
        filters,
    )
    stmt = apply_sort(stmt, sort, PRODUCT_VARIANT_SORT_COLUMNS)
    count_stmt = _apply_product_variant_filters(
        select(func.count(ProductVariant.id)).where(ProductVariant.tenant_id == tenant_id),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def create_product_variant(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: ProductVariantCreate,
    *,
    actor_user_id: uuid.UUID,
) -> ProductVariant:
    variant = await _create_variant_row(db, tenant_id, data)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="catalog.create_variant",
        entity_type="product_variant",
        entity_id=variant.id,
        after_json=_loggable_product_variant(variant),
    )
    await db.commit()
    await db.refresh(variant)
    return variant


async def update_product_variant(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    data: ProductVariantUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> ProductVariant:
    variant = await get_product_variant_by_id(db, tenant_id, product_variant_id)
    if variant is None:
        raise ProductVariantNotFound()
    before = _loggable_product_variant(variant)
    fields = data.model_dump(exclude_unset=True)
    if "catalog_item_id" in fields:
        await _ensure_active_catalog_item(db, tenant_id, fields["catalog_item_id"])
    if "base_unit_id" in fields:
        await _ensure_active_unit(db, fields["base_unit_id"])
        await _ensure_base_unit_change_is_safe(db, tenant_id, variant, fields["base_unit_id"])
    for key, value in fields.items():
        setattr(variant, key, value)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="catalog.update_variant",
        entity_type="product_variant",
        entity_id=variant.id,
        before_json=before,
        after_json=_loggable_product_variant(variant),
    )
    await db.commit()
    await db.refresh(variant)
    return variant


async def deactivate_product_variant(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    variant = await get_product_variant_by_id(db, tenant_id, product_variant_id)
    if variant is None:
        raise ProductVariantNotFound()
    before = _loggable_product_variant(variant)
    variant.is_active = False
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="catalog.deactivate_variant",
        entity_type="product_variant",
        entity_id=variant.id,
        before_json=before,
        after_json=_loggable_product_variant(variant),
    )
    await db.commit()


async def _create_variant_row(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: ProductVariantCreate,
) -> ProductVariant:
    await _ensure_active_catalog_item(db, tenant_id, data.catalog_item_id)
    await _ensure_active_unit(db, data.base_unit_id)
    sku = await generate_code(db, tenant_id, "product_variant")
    await _ensure_sku_available(db, tenant_id, sku)
    variant = ProductVariant(
        tenant_id=tenant_id,
        **data.model_dump(exclude={"sku", "create_base_unit"}),
        sku=sku,
    )
    db.add(variant)
    await db.flush()
    if data.create_base_unit:
        db.add(
            VariantUnit(
                tenant_id=tenant_id,
                product_variant_id=variant.id,
                unit_id=variant.base_unit_id,
                is_base_unit=True,
                is_purchase_unit=True,
                is_sales_unit=True,
                conversion_to_base=BASE_CONVERSION,
                allow_decimal_quantity=True,
            )
        )
    return variant


async def get_variant_unit_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    variant_unit_id: uuid.UUID,
) -> VariantUnit | None:
    return await db.scalar(
        select(VariantUnit).where(
            VariantUnit.tenant_id == tenant_id,
            VariantUnit.id == variant_unit_id,
        )
    )


async def list_variant_units(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: VariantUnitFilters,
    sort: tuple[SortSpec, ...],
) -> Page[VariantUnit]:
    stmt = _apply_variant_unit_filters(
        select(VariantUnit).where(VariantUnit.tenant_id == tenant_id),
        filters,
    )
    stmt = apply_sort(stmt, sort, VARIANT_UNIT_SORT_COLUMNS)
    count_stmt = _apply_variant_unit_filters(
        select(func.count(VariantUnit.id)).where(VariantUnit.tenant_id == tenant_id),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def create_variant_unit(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: VariantUnitCreate,
    *,
    actor_user_id: uuid.UUID,
) -> VariantUnit:
    variant = await _ensure_active_product_variant(db, tenant_id, data.product_variant_id)
    unit = await _ensure_active_unit(db, data.unit_id)
    await _ensure_unit_kind_compatible(db, variant, unit)
    await _ensure_variant_unit_available(db, tenant_id, data.product_variant_id, data.unit_id)
    await _ensure_base_unit_invariants(
        db,
        tenant_id,
        variant,
        data.unit_id,
        data.is_base_unit,
        data.conversion_to_base,
        data.is_active,
    )
    variant_unit = VariantUnit(tenant_id=tenant_id, **data.model_dump())
    db.add(variant_unit)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="catalog.create_variant_unit",
        entity_type="variant_unit",
        entity_id=variant_unit.id,
        after_json=_loggable_variant_unit(variant_unit),
    )
    await db.commit()
    await db.refresh(variant_unit)
    return variant_unit


async def update_variant_unit(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    variant_unit_id: uuid.UUID,
    data: VariantUnitUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> VariantUnit:
    variant_unit = await get_variant_unit_by_id(db, tenant_id, variant_unit_id)
    if variant_unit is None:
        raise VariantUnitNotFound()
    before = _loggable_variant_unit(variant_unit)
    fields = {
        key: value
        for key, value in data.model_dump(exclude_unset=True).items()
        if value is not None
    }
    await _ensure_variant_unit_configuration_is_mutable(db, variant_unit, fields)
    if variant_unit.is_base_unit and fields.get("is_active") is False:
        raise InvalidVariantBaseUnit()
    variant_id = fields.get("product_variant_id", variant_unit.product_variant_id)
    unit_id = fields.get("unit_id", variant_unit.unit_id)
    variant = await _ensure_active_product_variant(db, tenant_id, variant_id)
    unit = await _ensure_active_unit(db, unit_id)
    await _ensure_unit_kind_compatible(db, variant, unit)
    if variant_id != variant_unit.product_variant_id or unit_id != variant_unit.unit_id:
        await _ensure_variant_unit_available(
            db,
            tenant_id,
            variant_id,
            unit_id,
            variant_unit_id=variant_unit.id,
        )
    await _ensure_base_unit_invariants(
        db,
        tenant_id,
        variant,
        unit_id,
        fields.get("is_base_unit", variant_unit.is_base_unit),
        fields.get("conversion_to_base", variant_unit.conversion_to_base),
        fields.get("is_active", variant_unit.is_active),
        variant_unit_id=variant_unit.id,
    )
    for key, value in fields.items():
        setattr(variant_unit, key, value)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="catalog.update_variant_unit",
        entity_type="variant_unit",
        entity_id=variant_unit.id,
        before_json=before,
        after_json=_loggable_variant_unit(variant_unit),
    )
    await db.commit()
    await db.refresh(variant_unit)
    return variant_unit


async def deactivate_variant_unit(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    variant_unit_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    variant_unit = await get_variant_unit_by_id(db, tenant_id, variant_unit_id)
    if variant_unit is None:
        raise VariantUnitNotFound()
    if variant_unit.is_base_unit:
        raise InvalidVariantBaseUnit()
    before = _loggable_variant_unit(variant_unit)
    variant_unit.is_active = False
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="catalog.deactivate_variant_unit",
        entity_type="variant_unit",
        entity_id=variant_unit.id,
        before_json=before,
        after_json=_loggable_variant_unit(variant_unit),
    )
    await db.commit()


async def get_variant_barcode_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    variant_barcode_id: uuid.UUID,
) -> VariantBarcode | None:
    return await db.scalar(
        select(VariantBarcode).where(
            VariantBarcode.tenant_id == tenant_id,
            VariantBarcode.id == variant_barcode_id,
        )
    )


async def list_variant_barcodes(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: VariantBarcodeFilters,
    sort: tuple[SortSpec, ...],
) -> Page[VariantBarcode]:
    stmt = _apply_variant_barcode_filters(
        select(VariantBarcode).where(VariantBarcode.tenant_id == tenant_id),
        filters,
    )
    stmt = apply_sort(stmt, sort, VARIANT_BARCODE_SORT_COLUMNS)
    count_stmt = _apply_variant_barcode_filters(
        select(func.count(VariantBarcode.id)).where(VariantBarcode.tenant_id == tenant_id),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def create_variant_barcode(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: VariantBarcodeCreate,
    *,
    actor_user_id: uuid.UUID,
) -> VariantBarcode:
    await _ensure_active_product_variant(db, tenant_id, data.product_variant_id)
    if data.variant_unit_id is not None:
        await _ensure_active_variant_unit(
            db,
            tenant_id,
            data.product_variant_id,
            data.variant_unit_id,
        )
    await _ensure_barcode_available(db, tenant_id, data.barcode)
    if data.is_primary:
        await _ensure_primary_barcode_available(db, tenant_id, data.product_variant_id)
    barcode = VariantBarcode(tenant_id=tenant_id, **data.model_dump())
    db.add(barcode)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="catalog.create_variant_barcode",
        entity_type="variant_barcode",
        entity_id=barcode.id,
        after_json=_loggable_variant_barcode(barcode),
    )
    await db.commit()
    await db.refresh(barcode)
    return barcode


async def update_variant_barcode(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    variant_barcode_id: uuid.UUID,
    data: VariantBarcodeUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> VariantBarcode:
    barcode = await get_variant_barcode_by_id(db, tenant_id, variant_barcode_id)
    if barcode is None:
        raise VariantBarcodeNotFound()
    before = _loggable_variant_barcode(barcode)
    fields = data.model_dump(exclude_unset=True)
    variant_id = fields.get("product_variant_id", barcode.product_variant_id)
    await _ensure_active_product_variant(db, tenant_id, variant_id)
    variant_unit_id = fields.get("variant_unit_id", barcode.variant_unit_id)
    if variant_unit_id is not None:
        await _ensure_active_variant_unit(db, tenant_id, variant_id, variant_unit_id)
    new_barcode = fields.get("barcode")
    if new_barcode is not None and new_barcode != barcode.barcode:
        await _ensure_barcode_available(db, tenant_id, new_barcode, barcode_id=barcode.id)
    is_primary = fields.get("is_primary", barcode.is_primary)
    if is_primary and (
        variant_id != barcode.product_variant_id or not barcode.is_primary or not barcode.is_active
    ):
        await _ensure_primary_barcode_available(db, tenant_id, variant_id, barcode_id=barcode.id)
    for key, value in fields.items():
        setattr(barcode, key, value)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="catalog.update_variant_barcode",
        entity_type="variant_barcode",
        entity_id=barcode.id,
        before_json=before,
        after_json=_loggable_variant_barcode(barcode),
    )
    await db.commit()
    await db.refresh(barcode)
    return barcode


async def deactivate_variant_barcode(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    variant_barcode_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    barcode = await get_variant_barcode_by_id(db, tenant_id, variant_barcode_id)
    if barcode is None:
        raise VariantBarcodeNotFound()
    before = _loggable_variant_barcode(barcode)
    barcode.is_active = False
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="catalog.deactivate_variant_barcode",
        entity_type="variant_barcode",
        entity_id=barcode.id,
        before_json=before,
        after_json=_loggable_variant_barcode(barcode),
    )
    await db.commit()


async def create_variant_pos_profile(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: VariantPosProfileCreate,
    *,
    actor_user_id: uuid.UUID,
) -> VariantPosProfile:
    await _ensure_active_product_variant(db, tenant_id, data.product_variant_id)
    existing = await db.scalar(
        select(VariantPosProfile).where(
            VariantPosProfile.tenant_id == tenant_id,
            VariantPosProfile.product_variant_id == data.product_variant_id,
        )
    )
    if existing is not None:
        raise VariantPosProfileConflict()
    profile = VariantPosProfile(tenant_id=tenant_id, **data.model_dump())
    db.add(profile)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="catalog.create_variant_pos_profile",
        entity_type="variant_pos_profile",
        entity_id=profile.id,
        after_json=_loggable_variant_pos_profile(profile),
    )
    await db.commit()
    await db.refresh(profile)
    return profile


async def list_variant_pos_profiles(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: VariantPosProfileFilters,
    sort: tuple[SortSpec, ...],
) -> Page[VariantPosProfile]:
    stmt = _apply_variant_pos_profile_filters(
        select(VariantPosProfile).where(VariantPosProfile.tenant_id == tenant_id),
        filters,
    )
    stmt = apply_sort(stmt, sort, VARIANT_POS_PROFILE_SORT_COLUMNS)
    count_stmt = _apply_variant_pos_profile_filters(
        select(func.count(VariantPosProfile.id)).where(VariantPosProfile.tenant_id == tenant_id),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def get_variant_pos_profile_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    profile_id: uuid.UUID,
) -> VariantPosProfile | None:
    return await db.scalar(
        select(VariantPosProfile).where(
            VariantPosProfile.tenant_id == tenant_id,
            VariantPosProfile.id == profile_id,
        )
    )


async def update_variant_pos_profile(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    profile_id: uuid.UUID,
    data: VariantPosProfileUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> VariantPosProfile:
    profile = await get_variant_pos_profile_by_id(db, tenant_id, profile_id)
    if profile is None:
        raise VariantPosProfileNotFound()
    before = _loggable_variant_pos_profile(profile)
    fields = data.model_dump(exclude_unset=True)
    product_variant_id = fields.get("product_variant_id", profile.product_variant_id)
    if "product_variant_id" in fields:
        await _ensure_active_product_variant(db, tenant_id, product_variant_id)
        await _ensure_variant_pos_profile_available(
            db,
            tenant_id,
            product_variant_id,
            profile_id=profile.id,
        )
    for key, value in fields.items():
        setattr(profile, key, value)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="catalog.update_variant_pos_profile",
        entity_type="variant_pos_profile",
        entity_id=profile.id,
        before_json=before,
        after_json=_loggable_variant_pos_profile(profile),
    )
    await db.commit()
    await db.refresh(profile)
    return profile


async def delete_variant_pos_profile(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    profile_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    profile = await get_variant_pos_profile_by_id(db, tenant_id, profile_id)
    if profile is None:
        raise VariantPosProfileNotFound()
    before = _loggable_variant_pos_profile(profile)
    await db.delete(profile)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="catalog.delete_variant_pos_profile",
        entity_type="variant_pos_profile",
        entity_id=profile.id,
        before_json=before,
    )
    await db.commit()


async def create_variant_location_setting(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: VariantLocationSettingCreate,
    *,
    actor_user_id: uuid.UUID,
) -> VariantLocationSetting:
    await _ensure_active_product_variant(db, tenant_id, data.product_variant_id)
    await _ensure_active_location(db, tenant_id, data.location_id)
    if data.preferred_supplier_id is not None:
        await _ensure_active_supplier(db, tenant_id, data.preferred_supplier_id)
    existing = await db.scalar(
        select(VariantLocationSetting).where(
            VariantLocationSetting.tenant_id == tenant_id,
            VariantLocationSetting.product_variant_id == data.product_variant_id,
            VariantLocationSetting.location_id == data.location_id,
        )
    )
    if existing is not None:
        raise VariantLocationSettingConflict()
    setting = VariantLocationSetting(tenant_id=tenant_id, **data.model_dump())
    db.add(setting)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="catalog.create_variant_location_setting",
        entity_type="variant_location_setting",
        entity_id=setting.id,
        after_json=_loggable_variant_location_setting(setting),
    )
    await db.commit()
    await db.refresh(setting)
    return setting


async def list_variant_location_settings(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: VariantLocationSettingFilters,
    sort: tuple[SortSpec, ...],
) -> Page[VariantLocationSetting]:
    stmt = _apply_variant_location_setting_filters(
        select(VariantLocationSetting).where(VariantLocationSetting.tenant_id == tenant_id),
        filters,
    )
    stmt = apply_sort(stmt, sort, VARIANT_LOCATION_SETTING_SORT_COLUMNS)
    count_stmt = _apply_variant_location_setting_filters(
        select(func.count(VariantLocationSetting.id)).where(
            VariantLocationSetting.tenant_id == tenant_id
        ),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def get_variant_location_setting_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    setting_id: uuid.UUID,
) -> VariantLocationSetting | None:
    return await db.scalar(
        select(VariantLocationSetting).where(
            VariantLocationSetting.tenant_id == tenant_id,
            VariantLocationSetting.id == setting_id,
        )
    )


async def update_variant_location_setting(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    setting_id: uuid.UUID,
    data: VariantLocationSettingUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> VariantLocationSetting:
    setting = await get_variant_location_setting_by_id(db, tenant_id, setting_id)
    if setting is None:
        raise VariantLocationSettingNotFound()
    before = _loggable_variant_location_setting(setting)
    fields = data.model_dump(exclude_unset=True)
    product_variant_id = fields.get("product_variant_id", setting.product_variant_id)
    location_id = fields.get("location_id", setting.location_id)
    if "product_variant_id" in fields:
        await _ensure_active_product_variant(db, tenant_id, product_variant_id)
    if "location_id" in fields:
        await _ensure_active_location(db, tenant_id, location_id)
    if product_variant_id != setting.product_variant_id or location_id != setting.location_id:
        await _ensure_variant_location_setting_available(
            db,
            tenant_id,
            product_variant_id,
            location_id,
            setting_id=setting.id,
        )
    if "preferred_supplier_id" in fields and fields["preferred_supplier_id"] is not None:
        await _ensure_active_supplier(db, tenant_id, fields["preferred_supplier_id"])
    for key, value in fields.items():
        setattr(setting, key, value)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="catalog.update_variant_location_setting",
        entity_type="variant_location_setting",
        entity_id=setting.id,
        before_json=before,
        after_json=_loggable_variant_location_setting(setting),
    )
    await db.commit()
    await db.refresh(setting)
    return setting


async def delete_variant_location_setting(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    setting_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    setting = await get_variant_location_setting_by_id(db, tenant_id, setting_id)
    if setting is None:
        raise VariantLocationSettingNotFound()
    before = _loggable_variant_location_setting(setting)
    await db.delete(setting)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="catalog.delete_variant_location_setting",
        entity_type="variant_location_setting",
        entity_id=setting.id,
        before_json=before,
    )
    await db.commit()


async def get_option_group_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    option_group_id: uuid.UUID,
) -> CatalogItemOptionGroup | None:
    return await db.scalar(
        select(CatalogItemOptionGroup).where(
            CatalogItemOptionGroup.tenant_id == tenant_id,
            CatalogItemOptionGroup.id == option_group_id,
        )
    )


async def get_option_group_detail_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    option_group_id: uuid.UUID,
) -> CatalogItemOptionGroup | None:
    return await db.scalar(
        select(CatalogItemOptionGroup)
        .options(selectinload(CatalogItemOptionGroup.values))
        .where(
            CatalogItemOptionGroup.tenant_id == tenant_id,
            CatalogItemOptionGroup.id == option_group_id,
        )
    )


async def list_option_groups(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: CatalogItemOptionGroupFilters,
    sort: tuple[SortSpec, ...],
) -> Page[CatalogItemOptionGroup]:
    stmt = _apply_option_group_filters(
        select(CatalogItemOptionGroup).where(CatalogItemOptionGroup.tenant_id == tenant_id),
        filters,
    )
    stmt = apply_sort(stmt, sort, OPTION_GROUP_SORT_COLUMNS)
    count_stmt = _apply_option_group_filters(
        select(func.count(CatalogItemOptionGroup.id)).where(
            CatalogItemOptionGroup.tenant_id == tenant_id
        ),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def create_option_group(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: CatalogItemOptionGroupCreate,
    *,
    actor_user_id: uuid.UUID,
) -> CatalogItemOptionGroup:
    await _ensure_active_catalog_item(db, tenant_id, data.catalog_item_id)
    await _ensure_option_group_available(db, tenant_id, data.catalog_item_id, data.name)
    group = CatalogItemOptionGroup(tenant_id=tenant_id, **data.model_dump())
    db.add(group)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="catalog.create_option_group",
        entity_type="catalog_item_option_group",
        entity_id=group.id,
        after_json=_loggable_option_group(group),
    )
    await db.commit()
    await db.refresh(group)
    return group


async def update_option_group(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    option_group_id: uuid.UUID,
    data: CatalogItemOptionGroupUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> CatalogItemOptionGroup:
    group = await get_option_group_by_id(db, tenant_id, option_group_id)
    if group is None:
        raise CatalogItemOptionGroupNotFound()
    before = _loggable_option_group(group)
    fields = data.model_dump(exclude_unset=True)
    catalog_item_id = fields.get("catalog_item_id", group.catalog_item_id)
    if "catalog_item_id" in fields:
        await _ensure_active_catalog_item(db, tenant_id, catalog_item_id)
    name = fields.get("name", group.name)
    if catalog_item_id != group.catalog_item_id or name != group.name:
        await _ensure_option_group_available(
            db,
            tenant_id,
            catalog_item_id,
            name,
            option_group_id=group.id,
        )
    for key, value in fields.items():
        setattr(group, key, value)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="catalog.update_option_group",
        entity_type="catalog_item_option_group",
        entity_id=group.id,
        before_json=before,
        after_json=_loggable_option_group(group),
    )
    await db.commit()
    await db.refresh(group)
    return group


async def delete_option_group(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    option_group_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    group = await get_option_group_by_id(db, tenant_id, option_group_id)
    if group is None:
        raise CatalogItemOptionGroupNotFound()
    before = _loggable_option_group(group)
    await db.delete(group)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="catalog.delete_option_group",
        entity_type="catalog_item_option_group",
        entity_id=group.id,
        before_json=before,
    )
    await db.commit()


async def get_option_value_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    option_value_id: uuid.UUID,
) -> CatalogItemOptionValue | None:
    return await db.scalar(
        select(CatalogItemOptionValue).where(
            CatalogItemOptionValue.tenant_id == tenant_id,
            CatalogItemOptionValue.id == option_value_id,
        )
    )


async def list_option_values(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: CatalogItemOptionValueFilters,
    sort: tuple[SortSpec, ...],
) -> Page[CatalogItemOptionValue]:
    stmt = _apply_option_value_filters(
        select(CatalogItemOptionValue).where(CatalogItemOptionValue.tenant_id == tenant_id),
        filters,
    )
    stmt = apply_sort(stmt, sort, OPTION_VALUE_SORT_COLUMNS)
    count_stmt = _apply_option_value_filters(
        select(func.count(CatalogItemOptionValue.id)).where(
            CatalogItemOptionValue.tenant_id == tenant_id
        ),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def create_option_value(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: CatalogItemOptionValueCreate,
    *,
    actor_user_id: uuid.UUID,
) -> CatalogItemOptionValue:
    await _ensure_active_option_group(db, tenant_id, data.option_group_id)
    await _ensure_option_value_available(db, tenant_id, data.option_group_id, data.value)
    value = CatalogItemOptionValue(tenant_id=tenant_id, **data.model_dump())
    db.add(value)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="catalog.create_option_value",
        entity_type="catalog_item_option_value",
        entity_id=value.id,
        after_json=_loggable_option_value(value),
    )
    await db.commit()
    await db.refresh(value)
    return value


async def update_option_value(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    option_value_id: uuid.UUID,
    data: CatalogItemOptionValueUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> CatalogItemOptionValue:
    value = await get_option_value_by_id(db, tenant_id, option_value_id)
    if value is None:
        raise CatalogItemOptionValueNotFound()
    before = _loggable_option_value(value)
    fields = data.model_dump(exclude_unset=True)
    option_group_id = fields.get("option_group_id", value.option_group_id)
    if "option_group_id" in fields:
        await _ensure_active_option_group(db, tenant_id, option_group_id)
    new_value = fields.get("value", value.value)
    if option_group_id != value.option_group_id or new_value != value.value:
        await _ensure_option_value_available(
            db,
            tenant_id,
            option_group_id,
            new_value,
            option_value_id=value.id,
        )
    for key, item in fields.items():
        setattr(value, key, item)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="catalog.update_option_value",
        entity_type="catalog_item_option_value",
        entity_id=value.id,
        before_json=before,
        after_json=_loggable_option_value(value),
    )
    await db.commit()
    await db.refresh(value)
    return value


async def delete_option_value(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    option_value_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    value = await get_option_value_by_id(db, tenant_id, option_value_id)
    if value is None:
        raise CatalogItemOptionValueNotFound()
    before = _loggable_option_value(value)
    await db.delete(value)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="catalog.delete_option_value",
        entity_type="catalog_item_option_value",
        entity_id=value.id,
        before_json=before,
    )
    await db.commit()


async def get_variant_option_value_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    link_id: uuid.UUID,
) -> ProductVariantOptionValue | None:
    return await db.scalar(
        select(ProductVariantOptionValue).where(
            ProductVariantOptionValue.tenant_id == tenant_id,
            ProductVariantOptionValue.id == link_id,
        )
    )


async def list_variant_option_values(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: ProductVariantOptionValueFilters,
    sort: tuple[SortSpec, ...],
) -> Page[ProductVariantOptionValue]:
    stmt = _apply_variant_option_value_filters(
        select(ProductVariantOptionValue).where(ProductVariantOptionValue.tenant_id == tenant_id),
        filters,
    )
    stmt = apply_sort(stmt, sort, VARIANT_OPTION_VALUE_SORT_COLUMNS)
    count_stmt = _apply_variant_option_value_filters(
        select(func.count(ProductVariantOptionValue.id)).where(
            ProductVariantOptionValue.tenant_id == tenant_id
        ),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def create_variant_option_value(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: ProductVariantOptionValueCreate,
    *,
    actor_user_id: uuid.UUID,
) -> ProductVariantOptionValue:
    await _ensure_variant_option_value_link_valid(
        db,
        tenant_id,
        data.product_variant_id,
        data.option_value_id,
    )
    await _ensure_variant_option_value_available(
        db,
        tenant_id,
        data.product_variant_id,
        data.option_value_id,
    )
    link = ProductVariantOptionValue(tenant_id=tenant_id, **data.model_dump())
    db.add(link)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="catalog.create_variant_option_value",
        entity_type="product_variant_option_value",
        entity_id=link.id,
        after_json=_loggable_variant_option_value(link),
    )
    await db.commit()
    await db.refresh(link)
    return link


async def update_variant_option_value(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    link_id: uuid.UUID,
    data: ProductVariantOptionValueUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> ProductVariantOptionValue:
    link = await get_variant_option_value_by_id(db, tenant_id, link_id)
    if link is None:
        raise ProductVariantOptionValueNotFound()
    before = _loggable_variant_option_value(link)
    fields = data.model_dump(exclude_unset=True)
    product_variant_id = fields.get("product_variant_id", link.product_variant_id)
    option_value_id = fields.get("option_value_id", link.option_value_id)
    await _ensure_variant_option_value_link_valid(
        db,
        tenant_id,
        product_variant_id,
        option_value_id,
    )
    if product_variant_id != link.product_variant_id or option_value_id != link.option_value_id:
        await _ensure_variant_option_value_available(
            db,
            tenant_id,
            product_variant_id,
            option_value_id,
            link_id=link.id,
        )
    for key, value in fields.items():
        setattr(link, key, value)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="catalog.update_variant_option_value",
        entity_type="product_variant_option_value",
        entity_id=link.id,
        before_json=before,
        after_json=_loggable_variant_option_value(link),
    )
    await db.commit()
    await db.refresh(link)
    return link


async def delete_variant_option_value(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    link_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    link = await get_variant_option_value_by_id(db, tenant_id, link_id)
    if link is None:
        raise ProductVariantOptionValueNotFound()
    before = _loggable_variant_option_value(link)
    await db.delete(link)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="catalog.delete_variant_option_value",
        entity_type="product_variant_option_value",
        entity_id=link.id,
        before_json=before,
    )
    await db.commit()


def _apply_catalog_item_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: CatalogItemFilters,
) -> StmtT:
    search = search_clause(
        [CatalogItem.code, CatalogItem.name, CatalogItem.local_name, CatalogItem.description],
        filters.search,
    )
    if search is not None:
        stmt = stmt.where(search)
    if filters.category_id is not None:
        stmt = stmt.where(CatalogItem.category_id == filters.category_id)
    if filters.item_kind is not None:
        stmt = stmt.where(CatalogItem.item_kind == filters.item_kind)
    if filters.is_active is not None:
        stmt = stmt.where(CatalogItem.is_active == filters.is_active)
    return stmt


def _apply_product_variant_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: ProductVariantFilters,
) -> StmtT:
    search = search_clause(
        [ProductVariant.sku, ProductVariant.name, ProductVariant.local_name],
        filters.search,
    )
    if search is not None:
        stmt = stmt.where(search)
    if filters.catalog_item_id is not None:
        stmt = stmt.where(ProductVariant.catalog_item_id == filters.catalog_item_id)
    if filters.base_unit_id is not None:
        stmt = stmt.where(ProductVariant.base_unit_id == filters.base_unit_id)
    if filters.track_inventory is not None:
        stmt = stmt.where(ProductVariant.track_inventory == filters.track_inventory)
    if filters.is_active is not None:
        stmt = stmt.where(ProductVariant.is_active == filters.is_active)
    return stmt


def _apply_variant_unit_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: VariantUnitFilters,
) -> StmtT:
    if filters.product_variant_id is not None:
        stmt = stmt.where(VariantUnit.product_variant_id == filters.product_variant_id)
    if filters.unit_id is not None:
        stmt = stmt.where(VariantUnit.unit_id == filters.unit_id)
    if filters.is_base_unit is not None:
        stmt = stmt.where(VariantUnit.is_base_unit == filters.is_base_unit)
    if filters.is_purchase_unit is not None:
        stmt = stmt.where(VariantUnit.is_purchase_unit == filters.is_purchase_unit)
    if filters.is_sales_unit is not None:
        stmt = stmt.where(VariantUnit.is_sales_unit == filters.is_sales_unit)
    if filters.is_active is not None:
        stmt = stmt.where(VariantUnit.is_active == filters.is_active)
    return stmt


def _apply_variant_barcode_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: VariantBarcodeFilters,
) -> StmtT:
    if filters.product_variant_id is not None:
        stmt = stmt.where(VariantBarcode.product_variant_id == filters.product_variant_id)
    if filters.variant_unit_id is not None:
        stmt = stmt.where(VariantBarcode.variant_unit_id == filters.variant_unit_id)
    if filters.barcode is not None:
        stmt = stmt.where(VariantBarcode.barcode == filters.barcode)
    if filters.is_primary is not None:
        stmt = stmt.where(VariantBarcode.is_primary == filters.is_primary)
    if filters.is_active is not None:
        stmt = stmt.where(VariantBarcode.is_active == filters.is_active)
    return stmt


def _apply_variant_pos_profile_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: VariantPosProfileFilters,
) -> StmtT:
    if filters.product_variant_id is not None:
        stmt = stmt.where(VariantPosProfile.product_variant_id == filters.product_variant_id)
    if filters.is_visible is not None:
        stmt = stmt.where(VariantPosProfile.is_visible == filters.is_visible)
    return stmt


def _apply_variant_location_setting_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: VariantLocationSettingFilters,
) -> StmtT:
    if filters.product_variant_id is not None:
        stmt = stmt.where(VariantLocationSetting.product_variant_id == filters.product_variant_id)
    if filters.location_id is not None:
        stmt = stmt.where(VariantLocationSetting.location_id == filters.location_id)
    if filters.is_available is not None:
        stmt = stmt.where(VariantLocationSetting.is_available == filters.is_available)
    return stmt


def _apply_option_group_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: CatalogItemOptionGroupFilters,
) -> StmtT:
    if filters.catalog_item_id is not None:
        stmt = stmt.where(CatalogItemOptionGroup.catalog_item_id == filters.catalog_item_id)
    search = search_clause([CatalogItemOptionGroup.name], filters.search)
    if search is not None:
        stmt = stmt.where(search)
    return stmt


def _apply_option_value_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: CatalogItemOptionValueFilters,
) -> StmtT:
    if filters.option_group_id is not None:
        stmt = stmt.where(CatalogItemOptionValue.option_group_id == filters.option_group_id)
    search = search_clause([CatalogItemOptionValue.value], filters.search)
    if search is not None:
        stmt = stmt.where(search)
    return stmt


def _apply_variant_option_value_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: ProductVariantOptionValueFilters,
) -> StmtT:
    if filters.product_variant_id is not None:
        stmt = stmt.where(
            ProductVariantOptionValue.product_variant_id == filters.product_variant_id
        )
    if filters.option_value_id is not None:
        stmt = stmt.where(ProductVariantOptionValue.option_value_id == filters.option_value_id)
    return stmt


async def _ensure_active_category(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    category_id: uuid.UUID,
) -> ProductCategory:
    category = await db.scalar(
        select(ProductCategory).where(
            ProductCategory.tenant_id == tenant_id,
            ProductCategory.id == category_id,
            ProductCategory.is_active.is_(True),
        )
    )
    if category is None:
        raise InvalidCatalogCategory()
    return category


async def _ensure_active_catalog_item(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    catalog_item_id: uuid.UUID,
) -> CatalogItem:
    item = await db.scalar(
        select(CatalogItem).where(
            CatalogItem.tenant_id == tenant_id,
            CatalogItem.id == catalog_item_id,
            CatalogItem.is_active.is_(True),
        )
    )
    if item is None:
        raise InvalidCatalogItem()
    return item


async def _ensure_active_option_group(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    option_group_id: uuid.UUID,
) -> CatalogItemOptionGroup:
    group = await db.scalar(
        select(CatalogItemOptionGroup)
        .join(CatalogItem, CatalogItem.id == CatalogItemOptionGroup.catalog_item_id)
        .where(
            CatalogItemOptionGroup.tenant_id == tenant_id,
            CatalogItemOptionGroup.id == option_group_id,
            CatalogItem.is_active.is_(True),
        )
    )
    if group is None:
        raise InvalidCatalogItemOptionGroup()
    return group


async def _ensure_active_option_value(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    option_value_id: uuid.UUID,
) -> tuple[CatalogItemOptionValue, CatalogItemOptionGroup]:
    row = (
        await db.execute(
            select(CatalogItemOptionValue, CatalogItemOptionGroup)
            .join(
                CatalogItemOptionGroup,
                CatalogItemOptionGroup.id == CatalogItemOptionValue.option_group_id,
            )
            .join(CatalogItem, CatalogItem.id == CatalogItemOptionGroup.catalog_item_id)
            .where(
                CatalogItemOptionValue.tenant_id == tenant_id,
                CatalogItemOptionValue.id == option_value_id,
                CatalogItem.is_active.is_(True),
            )
        )
    ).one_or_none()
    if row is None:
        raise InvalidCatalogItemOptionValue()
    return row


async def _ensure_active_product_variant(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    variant_id: uuid.UUID,
) -> ProductVariant:
    variant = await db.scalar(
        select(ProductVariant).where(
            ProductVariant.tenant_id == tenant_id,
            ProductVariant.id == variant_id,
            ProductVariant.is_active.is_(True),
        )
    )
    if variant is None:
        raise ProductVariantNotFound()
    return variant


async def _ensure_option_group_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    catalog_item_id: uuid.UUID,
    name: str,
    *,
    option_group_id: uuid.UUID | None = None,
) -> None:
    existing = await db.scalar(
        select(CatalogItemOptionGroup).where(
            CatalogItemOptionGroup.tenant_id == tenant_id,
            CatalogItemOptionGroup.catalog_item_id == catalog_item_id,
            CatalogItemOptionGroup.name == name,
        )
    )
    if existing is not None and existing.id != option_group_id:
        raise CatalogItemOptionGroupConflict()


async def _ensure_option_value_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    option_group_id: uuid.UUID,
    value: str,
    *,
    option_value_id: uuid.UUID | None = None,
) -> None:
    existing = await db.scalar(
        select(CatalogItemOptionValue).where(
            CatalogItemOptionValue.tenant_id == tenant_id,
            CatalogItemOptionValue.option_group_id == option_group_id,
            CatalogItemOptionValue.value == value,
        )
    )
    if existing is not None and existing.id != option_value_id:
        raise CatalogItemOptionValueConflict()


async def _ensure_variant_option_value_link_valid(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    option_value_id: uuid.UUID,
) -> None:
    variant = await _ensure_active_product_variant(db, tenant_id, product_variant_id)
    _, group = await _ensure_active_option_value(db, tenant_id, option_value_id)
    if group.catalog_item_id != variant.catalog_item_id:
        raise InvalidProductVariantOptionValue()


async def _ensure_variant_option_value_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    option_value_id: uuid.UUID,
    *,
    link_id: uuid.UUID | None = None,
) -> None:
    _, group = await _ensure_active_option_value(db, tenant_id, option_value_id)
    existing_link = await db.scalar(
        select(ProductVariantOptionValue).where(
            ProductVariantOptionValue.tenant_id == tenant_id,
            ProductVariantOptionValue.product_variant_id == product_variant_id,
            ProductVariantOptionValue.option_value_id == option_value_id,
        )
    )
    if existing_link is not None and existing_link.id != link_id:
        raise ProductVariantOptionValueConflict()
    existing_group_link = await db.scalar(
        select(ProductVariantOptionValue)
        .join(
            CatalogItemOptionValue,
            CatalogItemOptionValue.id == ProductVariantOptionValue.option_value_id,
        )
        .where(
            ProductVariantOptionValue.tenant_id == tenant_id,
            ProductVariantOptionValue.product_variant_id == product_variant_id,
            CatalogItemOptionValue.option_group_id == group.id,
        )
    )
    if existing_group_link is not None and existing_group_link.id != link_id:
        raise ProductVariantOptionGroupConflict()


async def _ensure_active_unit(db: AsyncSession, unit_id: uuid.UUID) -> Unit:
    unit = await db.scalar(select(Unit).where(Unit.id == unit_id, Unit.is_active.is_(True)))
    if unit is None:
        raise InvalidCatalogUnit()
    return unit


async def _ensure_unit_kind_compatible(
    db: AsyncSession,
    variant: ProductVariant,
    unit: Unit,
) -> None:
    """Allow packaging conversions, but never silently mix physical dimensions."""
    base_unit = await db.scalar(select(Unit).where(Unit.id == variant.base_unit_id))
    if base_unit is None:
        raise InvalidCatalogUnit()
    if (
        unit.unit_kind != UnitKind.PACKAGE
        and base_unit.unit_kind != UnitKind.PACKAGE
        and unit.unit_kind != base_unit.unit_kind
    ):
        raise InvalidVariantUnitKind()


async def _ensure_active_variant_unit(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    variant_id: uuid.UUID,
    variant_unit_id: uuid.UUID,
) -> VariantUnit:
    variant_unit = await db.scalar(
        select(VariantUnit).where(
            VariantUnit.tenant_id == tenant_id,
            VariantUnit.id == variant_unit_id,
            VariantUnit.product_variant_id == variant_id,
            VariantUnit.is_active.is_(True),
        )
    )
    if variant_unit is None:
        raise InvalidVariantUnit()
    return variant_unit


async def _ensure_active_location(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    location_id: uuid.UUID,
) -> Location:
    location = await db.scalar(
        select(Location).where(
            Location.tenant_id == tenant_id,
            Location.id == location_id,
            Location.is_active.is_(True),
        )
    )
    if location is None:
        raise InvalidCatalogLocation()
    return location


async def _ensure_active_supplier(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
) -> Supplier:
    supplier = await db.scalar(
        select(Supplier).where(
            Supplier.tenant_id == tenant_id,
            Supplier.id == supplier_id,
            Supplier.status == PartyStatus.ACTIVE,
        )
    )
    if supplier is None:
        raise InvalidCatalogSupplier()
    return supplier


async def _ensure_sku_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    sku: str,
    *,
    variant_id: uuid.UUID | None = None,
) -> None:
    existing = await db.scalar(
        select(ProductVariant).where(
            ProductVariant.tenant_id == tenant_id,
            ProductVariant.sku == sku,
        )
    )
    if existing is not None and existing.id != variant_id:
        raise ProductVariantSkuConflict()


async def _generate_sku(db: AsyncSession, tenant_id: uuid.UUID) -> str:
    for _ in range(20):
        sku = f"VAR-{uuid.uuid4().hex[:10].upper()}"
        existing = await db.scalar(
            select(ProductVariant.id).where(
                ProductVariant.tenant_id == tenant_id,
                ProductVariant.sku == sku,
            )
        )
        if existing is None:
            return sku
    raise ProductVariantSkuConflict()


async def _ensure_variant_unit_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    variant_id: uuid.UUID,
    unit_id: uuid.UUID,
    *,
    variant_unit_id: uuid.UUID | None = None,
) -> None:
    existing = await db.scalar(
        select(VariantUnit).where(
            VariantUnit.tenant_id == tenant_id,
            VariantUnit.product_variant_id == variant_id,
            VariantUnit.unit_id == unit_id,
            VariantUnit.is_active.is_(True),
        )
    )
    if existing is not None and existing.id != variant_unit_id:
        raise VariantUnitConflict()


async def _ensure_variant_unit_configuration_is_mutable(
    db: AsyncSession,
    variant_unit: VariantUnit,
    fields: dict[str, Any],
) -> None:
    """Prevent retroactive changes to a UoM definition once another record references it.

    Document lines snapshot their conversion, but other configuration (barcode and
    price rules) also depends on this row.  Versioning preserves the meaning of
    every existing reference; deactivation remains available to retire a unit.
    """
    configuration_fields = {
        "product_variant_id",
        "unit_id",
        "is_base_unit",
        "is_purchase_unit",
        "is_sales_unit",
        "conversion_to_base",
        "allow_decimal_quantity",
        "rounding_precision",
        "requires_measured_quantity",
    }
    if not configuration_fields.intersection(fields):
        return

    variant_unit_id = variant_unit.id
    references = await db.scalar(
        select(
            or_(
                exists().where(VariantBarcode.variant_unit_id == variant_unit_id),
                exists().where(PriceRule.variant_unit_id == variant_unit_id),
                exists().where(PurchaseInvoiceLine.variant_unit_id == variant_unit_id),
                exists().where(SalesInvoiceLine.variant_unit_id == variant_unit_id),
                exists().where(StockAdjustmentLine.variant_unit_id == variant_unit_id),
                exists().where(StockTransferLine.variant_unit_id == variant_unit_id),
                exists().where(RepackOrderInput.variant_unit_id == variant_unit_id),
                exists().where(RepackOrderOutput.variant_unit_id == variant_unit_id),
            )
        )
    )
    if references:
        raise VariantUnitImmutable()


async def _ensure_base_unit_invariants(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    variant: ProductVariant,
    unit_id: uuid.UUID,
    is_base_unit: bool,
    conversion_to_base: Decimal,
    is_active: bool,
    *,
    variant_unit_id: uuid.UUID | None = None,
) -> None:
    if not is_base_unit:
        return
    if unit_id != variant.base_unit_id or conversion_to_base != BASE_CONVERSION:
        raise InvalidVariantBaseUnit()
    if not is_active:
        return
    existing = await db.scalar(
        select(VariantUnit).where(
            VariantUnit.tenant_id == tenant_id,
            VariantUnit.product_variant_id == variant.id,
            VariantUnit.is_base_unit.is_(True),
            VariantUnit.is_active.is_(True),
        )
    )
    if existing is not None and existing.id != variant_unit_id:
        raise VariantUnitBaseConflict()


async def _ensure_base_unit_change_is_safe(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    variant: ProductVariant,
    new_base_unit_id: uuid.UUID,
) -> None:
    if new_base_unit_id == variant.base_unit_id:
        return
    existing_base = await db.scalar(
        select(VariantUnit).where(
            VariantUnit.tenant_id == tenant_id,
            VariantUnit.product_variant_id == variant.id,
            VariantUnit.is_base_unit.is_(True),
            VariantUnit.is_active.is_(True),
        )
    )
    if existing_base is not None:
        raise InvalidVariantBaseUnit()


async def _ensure_barcode_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    barcode: str,
    *,
    barcode_id: uuid.UUID | None = None,
) -> None:
    existing = await db.scalar(
        select(VariantBarcode).where(
            VariantBarcode.tenant_id == tenant_id,
            VariantBarcode.barcode == barcode,
            VariantBarcode.is_active.is_(True),
        )
    )
    if existing is not None and existing.id != barcode_id:
        raise VariantBarcodeConflict()


async def _ensure_primary_barcode_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    variant_id: uuid.UUID,
    *,
    barcode_id: uuid.UUID | None = None,
) -> None:
    existing = await db.scalar(
        select(VariantBarcode).where(
            VariantBarcode.tenant_id == tenant_id,
            VariantBarcode.product_variant_id == variant_id,
            VariantBarcode.is_primary.is_(True),
            VariantBarcode.is_active.is_(True),
        )
    )
    if existing is not None and existing.id != barcode_id:
        raise VariantPrimaryBarcodeConflict()


async def _ensure_variant_pos_profile_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    *,
    profile_id: uuid.UUID | None = None,
) -> None:
    existing = await db.scalar(
        select(VariantPosProfile).where(
            VariantPosProfile.tenant_id == tenant_id,
            VariantPosProfile.product_variant_id == product_variant_id,
        )
    )
    if existing is not None and existing.id != profile_id:
        raise VariantPosProfileConflict()


async def _ensure_variant_location_setting_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    location_id: uuid.UUID,
    *,
    setting_id: uuid.UUID | None = None,
) -> None:
    existing = await db.scalar(
        select(VariantLocationSetting).where(
            VariantLocationSetting.tenant_id == tenant_id,
            VariantLocationSetting.product_variant_id == product_variant_id,
            VariantLocationSetting.location_id == location_id,
        )
    )
    if existing is not None and existing.id != setting_id:
        raise VariantLocationSettingConflict()


def _loggable_catalog_item(item: CatalogItem) -> dict[str, Any]:
    return {
        "code": item.code,
        "name": item.name,
        "local_name": item.local_name,
        "description": item.description,
        "category_id": str(item.category_id) if item.category_id is not None else None,
        "item_kind": item.item_kind.value,
        "is_active": item.is_active,
        "image_key": item.image_key,
    }


def _loggable_product_variant(variant: ProductVariant) -> dict[str, Any]:
    return {
        "catalog_item_id": str(variant.catalog_item_id),
        "sku": variant.sku,
        "name": variant.name,
        "local_name": variant.local_name,
        "base_unit_id": str(variant.base_unit_id),
        "default_sale_price": str(variant.default_sale_price)
        if variant.default_sale_price is not None
        else None,
        "default_purchase_cost": str(variant.default_purchase_cost)
        if variant.default_purchase_cost is not None
        else None,
        "track_inventory": variant.track_inventory,
        "track_batches": variant.track_batches,
        "track_expiry": variant.track_expiry,
        "is_active": variant.is_active,
    }


def _loggable_variant_unit(variant_unit: VariantUnit) -> dict[str, Any]:
    return {
        "product_variant_id": str(variant_unit.product_variant_id),
        "unit_id": str(variant_unit.unit_id),
        "is_base_unit": variant_unit.is_base_unit,
        "is_purchase_unit": variant_unit.is_purchase_unit,
        "is_sales_unit": variant_unit.is_sales_unit,
        "conversion_to_base": str(variant_unit.conversion_to_base),
        "allow_decimal_quantity": variant_unit.allow_decimal_quantity,
        "rounding_precision": str(variant_unit.rounding_precision),
        "requires_measured_quantity": variant_unit.requires_measured_quantity,
        "is_active": variant_unit.is_active,
    }


def _loggable_variant_barcode(barcode: VariantBarcode) -> dict[str, Any]:
    return {
        "product_variant_id": str(barcode.product_variant_id),
        "variant_unit_id": str(barcode.variant_unit_id)
        if barcode.variant_unit_id is not None
        else None,
        "barcode": barcode.barcode,
        "is_primary": barcode.is_primary,
        "is_active": barcode.is_active,
    }


def _loggable_variant_pos_profile(profile: VariantPosProfile) -> dict[str, Any]:
    return {
        "product_variant_id": str(profile.product_variant_id),
        "label": profile.label,
        "color": profile.color,
        "shape": profile.shape.value,
        "image_url": profile.image_url,
        "sort_order": profile.sort_order,
        "is_visible": profile.is_visible,
    }


def _loggable_variant_location_setting(setting: VariantLocationSetting) -> dict[str, Any]:
    return {
        "product_variant_id": str(setting.product_variant_id),
        "location_id": str(setting.location_id),
        "is_available": setting.is_available,
        "low_stock_quantity_base": str(setting.low_stock_quantity_base)
        if setting.low_stock_quantity_base is not None
        else None,
        "preferred_supplier_id": str(setting.preferred_supplier_id)
        if setting.preferred_supplier_id is not None
        else None,
    }


def _loggable_option_group(group: CatalogItemOptionGroup) -> dict[str, Any]:
    return {
        "catalog_item_id": str(group.catalog_item_id),
        "name": group.name,
        "position": group.position,
    }


def _loggable_option_value(value: CatalogItemOptionValue) -> dict[str, Any]:
    return {
        "option_group_id": str(value.option_group_id),
        "value": value.value,
        "position": value.position,
    }


def _loggable_variant_option_value(link: ProductVariantOptionValue) -> dict[str, Any]:
    return {
        "product_variant_id": str(link.product_variant_id),
        "option_value_id": str(link.option_value_id),
    }
