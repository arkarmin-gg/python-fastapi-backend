import asyncio
from dataclasses import dataclass
from decimal import Decimal

import src.registry  # noqa: F401
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.database import SessionFactory
from src.foundation_enums import CatalogItemKind, UnitKind
from src.modules.catalog.models import CatalogItem, ProductVariant, VariantUnit
from src.modules.codes.service import generate_code
from src.modules.product_categories.models import ProductCategory
from src.modules.tenants.models import Tenant
from src.modules.units.models import Unit

from scripts.seed import _get_or_create_tenant

BASE_CONVERSION = Decimal("1.00000000")


@dataclass(frozen=True)
class CatalogSeedRow:
    product: str
    category_code: str
    category_name: str
    base_unit_code: str
    alternative_unit_code: str
    conversion_to_base: Decimal
    typical_purchase: str
    typical_sale: str


@dataclass(frozen=True)
class UnitSeed:
    name_en: str
    name_my: str | None
    unit_kind: UnitKind


UNIT_ALIASES = {
    "BAG": "bag",
    "BOX": "box",
    "BTL": "bottle",
    "CAN": "can",
    "CTN": "carton",
    "DOZEN": "dozen",
    "GAL-5L": "gal-5l",
    "KG": "kg",
    "L": "l",
    "ML": "ml",
    "PACK": "pack",
    "PACK-100G": "pack-100g",
    "PACK-500G": "pack-500g",
    "BAG-10KG": "bag-10kg",
    "PAIR": "pair",
    "PCS": "piece",
    "ROLL": "roll",
    "SACHET": "sachet",
    "SHRINK": "shrink",
    "STRIP": "strip",
    "TRAY": "tray",
    "TUBE": "tube",
    "VISS": "viss",
}

UNIT_SEEDS = {
    "bag": UnitSeed("Bag", "အိတ်", UnitKind.PACKAGE),
    "bag-10kg": UnitSeed("10kg Bag", None, UnitKind.PACKAGE),
    "box": UnitSeed("Box", None, UnitKind.PACKAGE),
    "bottle": UnitSeed("Bottle", "ပုလင်း", UnitKind.PACKAGE),
    "can": UnitSeed("Can", "ဘူး", UnitKind.PACKAGE),
    "carton": UnitSeed("Carton", "ကတ်တွန်", UnitKind.PACKAGE),
    "dozen": UnitSeed("Dozen", None, UnitKind.COUNT),
    "gal-5l": UnitSeed("5L Gallon", None, UnitKind.VOLUME),
    "kg": UnitSeed("Kilogram", "ကီလိုဂရမ်", UnitKind.WEIGHT),
    "l": UnitSeed("Liter", None, UnitKind.VOLUME),
    "ml": UnitSeed("Milliliter", None, UnitKind.VOLUME),
    "pack": UnitSeed("Pack", "ထုပ်", UnitKind.PACKAGE),
    "pack-100g": UnitSeed("100g Pack", None, UnitKind.PACKAGE),
    "pack-500g": UnitSeed("500g Pack", None, UnitKind.PACKAGE),
    "pair": UnitSeed("Pair", None, UnitKind.COUNT),
    "piece": UnitSeed("Piece", "ခု", UnitKind.COUNT),
    "roll": UnitSeed("Roll", None, UnitKind.PACKAGE),
    "sachet": UnitSeed("Sachet", None, UnitKind.PACKAGE),
    "shrink": UnitSeed("Shrink Pack", None, UnitKind.PACKAGE),
    "strip": UnitSeed("Strip", None, UnitKind.PACKAGE),
    "tray": UnitSeed("Tray", None, UnitKind.PACKAGE),
    "tube": UnitSeed("Tube", None, UnitKind.PACKAGE),
    "viss": UnitSeed("Viss", "ပိဿာ", UnitKind.WEIGHT),
}

CATALOG_ROWS = (
    CatalogSeedRow(
        "Shwebo Paw San Rice",
        "rice-grain",
        "Rice & Grain",
        "KG",
        "VISS",
        Decimal("1.63293"),
        "BAG / VISS",
        "KG / VISS",
    ),
    CatalogSeedRow(
        "Emata Rice",
        "rice-grain",
        "Rice & Grain",
        "KG",
        "VISS",
        Decimal("1.63293"),
        "BAG / VISS",
        "KG / VISS",
    ),
    CatalogSeedRow(
        "Sticky Rice",
        "rice-grain",
        "Rice & Grain",
        "KG",
        "VISS",
        Decimal("1.63293"),
        "BAG",
        "KG / VISS",
    ),
    CatalogSeedRow(
        "Sugar", "pantry", "Pantry", "KG", "VISS", Decimal("1.63293"), "BAG", "KG / VISS"
    ),
    CatalogSeedRow(
        "Salt", "pantry", "Pantry", "KG", "PACK", Decimal("0.5"), "BAG", "KG / 500g pack"
    ),
    CatalogSeedRow(
        "Onion", "produce", "Produce", "KG", "VISS", Decimal("1.63293"), "BAG / VISS", "KG / VISS"
    ),
    CatalogSeedRow(
        "Garlic", "produce", "Produce", "KG", "VISS", Decimal("1.63293"), "VISS", "KG / VISS"
    ),
    CatalogSeedRow(
        "Potato", "produce", "Produce", "KG", "VISS", Decimal("1.63293"), "BAG", "KG / VISS"
    ),
    CatalogSeedRow(
        "Dried Chili", "pantry", "Pantry", "KG", "PACK-100G", Decimal("0.1"), "KG", "KG / 100g"
    ),
    CatalogSeedRow(
        "Chickpeas",
        "beans-pulses",
        "Beans & Pulses",
        "KG",
        "PACK-500G",
        Decimal("0.5"),
        "BAG",
        "KG / 500g",
    ),
    CatalogSeedRow(
        "Eggs", "eggs-dairy", "Eggs & Dairy", "PCS", "DOZEN", Decimal("12"), "TRAY", "PCS / dozen"
    ),
    CatalogSeedRow(
        "Eggs", "eggs-dairy", "Eggs & Dairy", "PCS", "TRAY", Decimal("30"), "TRAY", "PCS / tray"
    ),
    CatalogSeedRow(
        "Drinking Water",
        "beverages",
        "Beverages",
        "BTL",
        "SHRINK",
        Decimal("12"),
        "SHRINK",
        "BTL / shrink",
    ),
    CatalogSeedRow(
        "Drinking Water",
        "beverages",
        "Beverages",
        "BTL",
        "CTN",
        Decimal("24"),
        "CTN",
        "BTL / carton",
    ),
    CatalogSeedRow(
        "Soft Drink Can",
        "beverages",
        "Beverages",
        "CAN",
        "CTN",
        Decimal("24"),
        "CTN",
        "CAN / carton",
    ),
    CatalogSeedRow(
        "Energy Drink", "beverages", "Beverages", "CAN", "CTN", Decimal("24"), "CTN", "CAN"
    ),
    CatalogSeedRow(
        "Beer-style non-alcoholic malt drink",
        "beverages",
        "Beverages",
        "CAN",
        "CTN",
        Decimal("24"),
        "CTN",
        "CAN",
    ),
    CatalogSeedRow(
        "Instant Noodles",
        "instant-food",
        "Instant Food",
        "PACK",
        "CTN",
        Decimal("30"),
        "CTN",
        "PACK / carton",
    ),
    CatalogSeedRow(
        "Coffee Mix Sachet",
        "coffee-tea",
        "Coffee & Tea",
        "SACHET",
        "BAG",
        Decimal("30"),
        "BAG",
        "SACHET / bag",
    ),
    CatalogSeedRow(
        "Coffee Mix Sachet",
        "coffee-tea",
        "Coffee & Tea",
        "SACHET",
        "CTN",
        Decimal("360"),
        "CTN",
        "sachet",
    ),
    CatalogSeedRow(
        "Tea Mix Sachet",
        "coffee-tea",
        "Coffee & Tea",
        "SACHET",
        "BAG",
        Decimal("30"),
        "BAG",
        "SACHET / bag",
    ),
    CatalogSeedRow(
        "Condensed Milk", "eggs-dairy", "Eggs & Dairy", "CAN", "CTN", Decimal("48"), "CTN", "CAN"
    ),
    CatalogSeedRow(
        "Evaporated Milk", "eggs-dairy", "Eggs & Dairy", "CAN", "CTN", Decimal("48"), "CTN", "CAN"
    ),
    CatalogSeedRow(
        "Fish Sauce", "sauces-oils", "Sauces & Oils", "BTL", "CTN", Decimal("12"), "CTN", "BTL"
    ),
    CatalogSeedRow(
        "Soy Sauce", "sauces-oils", "Sauces & Oils", "BTL", "CTN", Decimal("12"), "CTN", "BTL"
    ),
    CatalogSeedRow(
        "Cooking Oil", "sauces-oils", "Sauces & Oils", "BTL", "CTN", Decimal("12"), "CTN", "BTL"
    ),
    CatalogSeedRow(
        "Bulk Cooking Oil",
        "sauces-oils",
        "Sauces & Oils",
        "L",
        "ML",
        Decimal("0.001"),
        "drum",
        "L / fractional L",
    ),
    CatalogSeedRow(
        "Bulk Cooking Oil",
        "sauces-oils",
        "Sauces & Oils",
        "L",
        "GAL-5L",
        Decimal("5"),
        "gallon/container",
        "L / container",
    ),
    CatalogSeedRow(
        "Laundry Powder",
        "household",
        "Household",
        "KG",
        "PACK-500G",
        Decimal("0.5"),
        "BAG",
        "PACK / KG",
    ),
    CatalogSeedRow(
        "Laundry Powder", "household", "Household", "KG", "BAG-10KG", Decimal("10"), "BAG", "KG"
    ),
    CatalogSeedRow(
        "Dishwashing Liquid", "household", "Household", "BTL", "CTN", Decimal("12"), "CTN", "BTL"
    ),
    CatalogSeedRow(
        "Shampoo Sachet",
        "personal-care",
        "Personal Care",
        "SACHET",
        "STRIP",
        Decimal("12"),
        "BAG",
        "SACHET / strip",
    ),
    CatalogSeedRow(
        "Shampoo Sachet",
        "personal-care",
        "Personal Care",
        "SACHET",
        "BAG",
        Decimal("144"),
        "BAG",
        "SACHET",
    ),
    CatalogSeedRow(
        "Soap Bar",
        "personal-care",
        "Personal Care",
        "PCS",
        "PACK",
        Decimal("4"),
        "CTN",
        "PCS / pack",
    ),
    CatalogSeedRow(
        "Soap Bar", "personal-care", "Personal Care", "PCS", "CTN", Decimal("72"), "CTN", "PCS"
    ),
    CatalogSeedRow(
        "Toothpaste", "personal-care", "Personal Care", "TUBE", "BOX", Decimal("12"), "BOX", "TUBE"
    ),
    CatalogSeedRow(
        "Tissue Roll",
        "household",
        "Household",
        "ROLL",
        "PACK",
        Decimal("10"),
        "PACK",
        "ROLL / pack",
    ),
    CatalogSeedRow(
        "Batteries AA", "household", "Household", "PCS", "PAIR", Decimal("2"), "BOX", "pair"
    ),
    CatalogSeedRow(
        "Batteries AA", "household", "Household", "PCS", "BOX", Decimal("40"), "BOX", "PCS / pair"
    ),
    CatalogSeedRow(
        "Candles", "household", "Household", "PCS", "PACK", Decimal("10"), "PACK", "PACK / PCS"
    ),
)


def _unit_code(raw_code: str) -> str:
    return UNIT_ALIASES[raw_code.upper()]


def _mentions_unit(text: str, raw_unit_code: str) -> bool:
    normalized = text.upper()
    aliases = {
        "BTL": ("BTL", "BOTTLE"),
        "CTN": ("CTN", "CARTON"),
        "PCS": ("PCS", "PIECE"),
        "PACK-100G": ("PACK-100G", "100G"),
        "PACK-500G": ("PACK-500G", "500G"),
        "GAL-5L": ("GAL-5L", "GALLON", "CONTAINER"),
        "L": ("L", "FRACTIONAL L"),
    }
    candidates = aliases.get(raw_unit_code.upper(), (raw_unit_code.upper(),))
    return any(candidate in normalized for candidate in candidates)


async def _ensure_unit(db: AsyncSession, raw_code: str) -> Unit:
    code = _unit_code(raw_code)
    seed = UNIT_SEEDS[code]
    unit = await db.scalar(select(Unit).where(Unit.code == code))
    if unit is not None:
        unit.name_en = seed.name_en
        unit.name_my = seed.name_my
        unit.unit_kind = seed.unit_kind
        unit.is_active = True
        return unit
    unit = Unit(
        code=code,
        name_en=seed.name_en,
        name_my=seed.name_my,
        unit_kind=seed.unit_kind,
    )
    db.add(unit)
    await db.flush()
    return unit


async def _ensure_category(
    db: AsyncSession,
    tenant: Tenant,
    *,
    code: str,
    name: str,
) -> ProductCategory:
    category = await db.scalar(
        select(ProductCategory).where(
            ProductCategory.tenant_id == tenant.id,
            ProductCategory.code == code,
        )
    )
    if category is None:
        category = await db.scalar(
            select(ProductCategory).where(
                ProductCategory.tenant_id == tenant.id,
                ProductCategory.name == name,
            )
        )
    if category is None:
        category = ProductCategory(
            tenant_id=tenant.id,
            code=await generate_code(db, tenant.id, "product_category"),
            name=name,
        )
        db.add(category)
        await db.flush()
    elif category.name != name:
        category.name = name
    return category


async def _ensure_catalog_item(
    db: AsyncSession,
    tenant: Tenant,
    row: CatalogSeedRow,
    category: ProductCategory,
) -> CatalogItem:
    item = await db.scalar(
        select(CatalogItem).where(
            CatalogItem.tenant_id == tenant.id,
            CatalogItem.name == row.product,
        )
    )
    if item is None:
        item = CatalogItem(
            tenant_id=tenant.id,
            code=await generate_code(db, tenant.id, "catalog_item"),
            name=row.product,
            category_id=category.id,
            item_kind=CatalogItemKind.STOCKED,
        )
        db.add(item)
        await db.flush()
    else:
        item.category_id = category.id
        item.item_kind = CatalogItemKind.STOCKED
        item.is_active = True
    return item


async def _ensure_variant(
    db: AsyncSession,
    tenant: Tenant,
    item: CatalogItem,
    row: CatalogSeedRow,
    base_unit: Unit,
) -> ProductVariant:
    variant = await db.scalar(
        select(ProductVariant).where(
            ProductVariant.tenant_id == tenant.id,
            ProductVariant.catalog_item_id == item.id,
            ProductVariant.name == row.product,
        )
    )
    if variant is None:
        variant = ProductVariant(
            tenant_id=tenant.id,
            catalog_item_id=item.id,
            sku=await generate_code(db, tenant.id, "product_variant"),
            name=row.product,
            base_unit_id=base_unit.id,
            track_inventory=True,
            track_batches=True,
            track_expiry=False,
        )
        db.add(variant)
        await db.flush()
    else:
        variant.catalog_item_id = item.id
        variant.name = row.product
        variant.base_unit_id = base_unit.id
        variant.track_inventory = True
        variant.track_batches = True
        variant.is_active = True
    return variant


async def _ensure_variant_unit(
    db: AsyncSession,
    tenant: Tenant,
    variant: ProductVariant,
    unit: Unit,
    *,
    is_base_unit: bool,
    conversion_to_base: Decimal,
    is_purchase_unit: bool,
    is_sales_unit: bool,
    allow_decimal_quantity: bool,
) -> VariantUnit:
    variant_unit = await db.scalar(
        select(VariantUnit).where(
            VariantUnit.tenant_id == tenant.id,
            VariantUnit.product_variant_id == variant.id,
            VariantUnit.unit_id == unit.id,
            VariantUnit.is_active.is_(True),
        )
    )
    if variant_unit is None:
        variant_unit = VariantUnit(
            tenant_id=tenant.id,
            product_variant_id=variant.id,
            unit_id=unit.id,
            is_base_unit=is_base_unit,
            is_purchase_unit=is_purchase_unit,
            is_sales_unit=is_sales_unit,
            conversion_to_base=conversion_to_base,
            allow_decimal_quantity=allow_decimal_quantity,
        )
        db.add(variant_unit)
        await db.flush()
    else:
        variant_unit.is_base_unit = is_base_unit
        variant_unit.is_purchase_unit = is_purchase_unit
        variant_unit.is_sales_unit = is_sales_unit
        variant_unit.conversion_to_base = conversion_to_base
        variant_unit.allow_decimal_quantity = allow_decimal_quantity
    return variant_unit


async def seed_catalog() -> None:
    async with SessionFactory() as db:
        tenant = await _get_or_create_tenant(db)
        units_by_raw_code: dict[str, Unit] = {}
        categories_by_code: dict[str, ProductCategory] = {}
        variants_by_product: dict[str, ProductVariant] = {}

        for row in CATALOG_ROWS:
            units_by_raw_code[row.base_unit_code] = await _ensure_unit(db, row.base_unit_code)
            units_by_raw_code[row.alternative_unit_code] = await _ensure_unit(
                db,
                row.alternative_unit_code,
            )
            category = categories_by_code.get(row.category_code)
            if category is None:
                category = await _ensure_category(
                    db,
                    tenant,
                    code=row.category_code,
                    name=row.category_name,
                )
                categories_by_code[row.category_code] = category

            item = await _ensure_catalog_item(db, tenant, row, category)
            base_unit = units_by_raw_code[row.base_unit_code]
            variant = variants_by_product.get(row.product)
            if variant is None:
                variant = await _ensure_variant(db, tenant, item, row, base_unit)
                variants_by_product[row.product] = variant
            await _ensure_variant_unit(
                db,
                tenant,
                variant,
                base_unit,
                is_base_unit=True,
                conversion_to_base=BASE_CONVERSION,
                is_purchase_unit=True,
                is_sales_unit=True,
                allow_decimal_quantity=base_unit.unit_kind in {UnitKind.WEIGHT, UnitKind.VOLUME},
            )

            alternative_unit = units_by_raw_code[row.alternative_unit_code]
            await _ensure_variant_unit(
                db,
                tenant,
                variant,
                alternative_unit,
                is_base_unit=False,
                conversion_to_base=row.conversion_to_base,
                is_purchase_unit=_mentions_unit(row.typical_purchase, row.alternative_unit_code),
                is_sales_unit=_mentions_unit(row.typical_sale, row.alternative_unit_code),
                allow_decimal_quantity=False,
            )

        await db.commit()

    print(
        f"Catalog seed complete: tenant {tenant.code!r}, "
        f"{len(categories_by_code)} categories, {len(variants_by_product)} variants, "
        f"{len(CATALOG_ROWS)} catalog unit rows."
    )


if __name__ == "__main__":
    asyncio.run(seed_catalog())
