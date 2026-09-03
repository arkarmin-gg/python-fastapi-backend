import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import Query
from pydantic import Field, computed_field, model_validator

from src.foundation_enums import CatalogItemKind, PosTileShape
from src.pagination import Page
from src.query_filters import build_query_model, normalize_search
from src.schemas import RequestSchema, ResponseSchema
from src.storage import service as storage_service


class VariantUnitRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    product_variant_id: uuid.UUID
    unit_id: uuid.UUID
    is_base_unit: bool
    is_purchase_unit: bool
    is_sales_unit: bool
    conversion_to_base: Decimal
    allow_decimal_quantity: bool
    rounding_precision: Decimal
    requires_measured_quantity: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class VariantBarcodeRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    product_variant_id: uuid.UUID
    variant_unit_id: uuid.UUID | None
    barcode: str
    is_primary: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class VariantPosProfileRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    product_variant_id: uuid.UUID
    label: str | None
    color: str | None
    shape: PosTileShape
    image_url: str | None
    sort_order: int
    is_visible: bool
    created_at: datetime
    updated_at: datetime


class VariantLocationSettingRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    product_variant_id: uuid.UUID
    location_id: uuid.UUID
    is_available: bool
    low_stock_quantity_base: Decimal | None
    preferred_supplier_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class CatalogItemOptionValueRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    option_group_id: uuid.UUID
    value: str
    position: int
    created_at: datetime
    updated_at: datetime


class CatalogItemOptionGroupRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    catalog_item_id: uuid.UUID
    name: str
    position: int
    created_at: datetime
    updated_at: datetime


class CatalogItemOptionGroupDetailRead(CatalogItemOptionGroupRead):
    values: list[CatalogItemOptionValueRead] = Field(default_factory=list)


class ProductVariantOptionValueRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    product_variant_id: uuid.UUID
    option_value_id: uuid.UUID


class ProductVariantRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    catalog_item_id: uuid.UUID
    sku: str
    name: str
    local_name: str | None
    base_unit_id: uuid.UUID
    default_sale_price: Decimal | None
    default_purchase_cost: Decimal | None
    track_inventory: bool
    track_batches: bool
    track_expiry: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProductVariantDetailRead(ProductVariantRead):
    variant_units: list[VariantUnitRead] = Field(default_factory=list)
    barcodes: list[VariantBarcodeRead] = Field(default_factory=list)
    pos_profile: VariantPosProfileRead | None = None
    location_settings: list[VariantLocationSettingRead] = Field(default_factory=list)
    option_values: list[ProductVariantOptionValueRead] = Field(default_factory=list)


class CatalogItemRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    code: str
    name: str
    local_name: str | None
    description: str | None
    category_id: uuid.UUID | None
    item_kind: CatalogItemKind
    is_active: bool
    image_key: str | None = Field(exclude=True, repr=False)
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def image_url(self) -> str | None:
        return storage_service.presigned_url(self.image_key)


class CatalogItemDetailRead(CatalogItemRead):
    variants: list[ProductVariantDetailRead] = Field(default_factory=list)
    option_groups: list[CatalogItemOptionGroupDetailRead] = Field(default_factory=list)


class BarcodeLookupRead(ResponseSchema):
    catalog_item: CatalogItemRead
    product_variant: ProductVariantRead
    variant_unit: VariantUnitRead | None
    barcode: VariantBarcodeRead


CatalogItemListResponse = Page[CatalogItemRead]
ProductVariantListResponse = Page[ProductVariantRead]
VariantUnitListResponse = Page[VariantUnitRead]
VariantBarcodeListResponse = Page[VariantBarcodeRead]
VariantPosProfileListResponse = Page[VariantPosProfileRead]
VariantLocationSettingListResponse = Page[VariantLocationSettingRead]
CatalogItemOptionGroupListResponse = Page[CatalogItemOptionGroupRead]
CatalogItemOptionValueListResponse = Page[CatalogItemOptionValueRead]
ProductVariantOptionValueListResponse = Page[ProductVariantOptionValueRead]


class CatalogItemFilters(RequestSchema):
    search: str | None = None
    category_id: uuid.UUID | None = None
    item_kind: CatalogItemKind | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def normalize(self):
        self.search = normalize_search(self.search)
        return self


def catalog_item_filters(
    search: Annotated[str | None, Query()] = None,
    category_id: Annotated[uuid.UUID | None, Query()] = None,
    item_kind: Annotated[CatalogItemKind | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = None,
) -> CatalogItemFilters:
    return build_query_model(
        CatalogItemFilters,
        search=search,
        category_id=category_id,
        item_kind=item_kind,
        is_active=is_active,
    )


class ProductVariantFilters(RequestSchema):
    search: str | None = None
    catalog_item_id: uuid.UUID | None = None
    base_unit_id: uuid.UUID | None = None
    track_inventory: bool | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def normalize(self):
        self.search = normalize_search(self.search)
        return self


def product_variant_filters(
    search: Annotated[str | None, Query()] = None,
    catalog_item_id: Annotated[uuid.UUID | None, Query()] = None,
    base_unit_id: Annotated[uuid.UUID | None, Query()] = None,
    track_inventory: Annotated[bool | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = None,
) -> ProductVariantFilters:
    return build_query_model(
        ProductVariantFilters,
        search=search,
        catalog_item_id=catalog_item_id,
        base_unit_id=base_unit_id,
        track_inventory=track_inventory,
        is_active=is_active,
    )


class VariantUnitFilters(RequestSchema):
    product_variant_id: uuid.UUID | None = None
    unit_id: uuid.UUID | None = None
    is_base_unit: bool | None = None
    is_purchase_unit: bool | None = None
    is_sales_unit: bool | None = None
    is_active: bool | None = None


def variant_unit_filters(
    product_variant_id: Annotated[uuid.UUID | None, Query()] = None,
    unit_id: Annotated[uuid.UUID | None, Query()] = None,
    is_base_unit: Annotated[bool | None, Query()] = None,
    is_purchase_unit: Annotated[bool | None, Query()] = None,
    is_sales_unit: Annotated[bool | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = None,
) -> VariantUnitFilters:
    return build_query_model(
        VariantUnitFilters,
        product_variant_id=product_variant_id,
        unit_id=unit_id,
        is_base_unit=is_base_unit,
        is_purchase_unit=is_purchase_unit,
        is_sales_unit=is_sales_unit,
        is_active=is_active,
    )


class VariantBarcodeFilters(RequestSchema):
    product_variant_id: uuid.UUID | None = None
    variant_unit_id: uuid.UUID | None = None
    barcode: str | None = Field(default=None, min_length=1, max_length=120)
    is_primary: bool | None = None
    is_active: bool | None = None


def variant_barcode_filters(
    product_variant_id: Annotated[uuid.UUID | None, Query()] = None,
    variant_unit_id: Annotated[uuid.UUID | None, Query()] = None,
    barcode: Annotated[str | None, Query(min_length=1, max_length=120)] = None,
    is_primary: Annotated[bool | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = None,
) -> VariantBarcodeFilters:
    return build_query_model(
        VariantBarcodeFilters,
        product_variant_id=product_variant_id,
        variant_unit_id=variant_unit_id,
        barcode=barcode,
        is_primary=is_primary,
        is_active=is_active,
    )


class VariantPosProfileFilters(RequestSchema):
    product_variant_id: uuid.UUID | None = None
    is_visible: bool | None = None


def variant_pos_profile_filters(
    product_variant_id: Annotated[uuid.UUID | None, Query()] = None,
    is_visible: Annotated[bool | None, Query()] = None,
) -> VariantPosProfileFilters:
    return build_query_model(
        VariantPosProfileFilters,
        product_variant_id=product_variant_id,
        is_visible=is_visible,
    )


class VariantLocationSettingFilters(RequestSchema):
    product_variant_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None
    is_available: bool | None = None


def variant_location_setting_filters(
    product_variant_id: Annotated[uuid.UUID | None, Query()] = None,
    location_id: Annotated[uuid.UUID | None, Query()] = None,
    is_available: Annotated[bool | None, Query()] = None,
) -> VariantLocationSettingFilters:
    return build_query_model(
        VariantLocationSettingFilters,
        product_variant_id=product_variant_id,
        location_id=location_id,
        is_available=is_available,
    )


class CatalogItemOptionGroupFilters(RequestSchema):
    catalog_item_id: uuid.UUID | None = None
    search: str | None = None

    @model_validator(mode="after")
    def normalize(self):
        self.search = normalize_search(self.search)
        return self


def catalog_item_option_group_filters(
    catalog_item_id: Annotated[uuid.UUID | None, Query()] = None,
    search: Annotated[str | None, Query()] = None,
) -> CatalogItemOptionGroupFilters:
    return build_query_model(
        CatalogItemOptionGroupFilters,
        catalog_item_id=catalog_item_id,
        search=search,
    )


class CatalogItemOptionValueFilters(RequestSchema):
    option_group_id: uuid.UUID | None = None
    search: str | None = None

    @model_validator(mode="after")
    def normalize(self):
        self.search = normalize_search(self.search)
        return self


def catalog_item_option_value_filters(
    option_group_id: Annotated[uuid.UUID | None, Query()] = None,
    search: Annotated[str | None, Query()] = None,
) -> CatalogItemOptionValueFilters:
    return build_query_model(
        CatalogItemOptionValueFilters,
        option_group_id=option_group_id,
        search=search,
    )


class ProductVariantOptionValueFilters(RequestSchema):
    product_variant_id: uuid.UUID | None = None
    option_value_id: uuid.UUID | None = None


def product_variant_option_value_filters(
    product_variant_id: Annotated[uuid.UUID | None, Query()] = None,
    option_value_id: Annotated[uuid.UUID | None, Query()] = None,
) -> ProductVariantOptionValueFilters:
    return build_query_model(
        ProductVariantOptionValueFilters,
        product_variant_id=product_variant_id,
        option_value_id=option_value_id,
    )


class VariantPosProfileInput(RequestSchema):
    label: str | None = Field(default=None, min_length=1, max_length=80)
    color: str | None = Field(default=None, min_length=1, max_length=20)
    shape: PosTileShape = PosTileShape.SQUARE
    image_url: str | None = Field(default=None, min_length=1, max_length=500)
    sort_order: int = 0
    is_visible: bool = True


class VariantLocationSettingInput(RequestSchema):
    location_id: uuid.UUID
    is_available: bool = True
    low_stock_quantity_base: Decimal | None = Field(default=None, ge=0)
    preferred_supplier_id: uuid.UUID | None = None


class CatalogItemVariantCreate(RequestSchema):
    name: str = Field(min_length=1, max_length=160)
    local_name: str | None = Field(default=None, min_length=1, max_length=160)
    base_unit_id: uuid.UUID
    default_sale_price: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=4)
    default_purchase_cost: Decimal | None = Field(
        default=None, ge=0, max_digits=20, decimal_places=4
    )
    track_inventory: bool = True
    track_batches: bool = True
    track_expiry: bool = False
    barcode: str | None = Field(default=None, min_length=1, max_length=120)
    pos_profile: VariantPosProfileInput | None = None
    location_settings: list[VariantLocationSettingInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def _no_duplicate_locations(self) -> "CatalogItemVariantCreate":
        location_ids = [setting.location_id for setting in self.location_settings]
        if len(location_ids) != len(set(location_ids)):
            raise ValueError("location_settings must not repeat the same location_id.")
        return self


class CatalogItemCreate(RequestSchema):
    name: str = Field(min_length=1, max_length=240)
    local_name: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = None
    category_id: uuid.UUID | None = None
    item_kind: CatalogItemKind = CatalogItemKind.STOCKED
    is_active: bool = True
    pos_profile: VariantPosProfileInput | None = None
    variants: list[CatalogItemVariantCreate] = Field(min_length=1)


class CatalogItemUpdate(RequestSchema):
    name: str | None = Field(default=None, min_length=1, max_length=240)
    local_name: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = None
    category_id: uuid.UUID | None = None
    item_kind: CatalogItemKind | None = None
    is_active: bool | None = None


class ProductVariantCreate(RequestSchema):
    catalog_item_id: uuid.UUID
    name: str = Field(min_length=1, max_length=160)
    local_name: str | None = Field(default=None, min_length=1, max_length=160)
    base_unit_id: uuid.UUID
    default_sale_price: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=4)
    default_purchase_cost: Decimal | None = Field(
        default=None, ge=0, max_digits=20, decimal_places=4
    )
    track_inventory: bool = True
    track_batches: bool = True
    track_expiry: bool = False
    is_active: bool = True
    create_base_unit: bool = True


class ProductVariantUpdate(RequestSchema):
    catalog_item_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=160)
    local_name: str | None = Field(default=None, min_length=1, max_length=160)
    base_unit_id: uuid.UUID | None = None
    default_sale_price: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=4)
    default_purchase_cost: Decimal | None = Field(
        default=None, ge=0, max_digits=20, decimal_places=4
    )
    track_inventory: bool | None = None
    track_batches: bool | None = None
    track_expiry: bool | None = None
    is_active: bool | None = None


class VariantUnitCreate(RequestSchema):
    product_variant_id: uuid.UUID
    unit_id: uuid.UUID
    is_base_unit: bool = False
    is_purchase_unit: bool = False
    is_sales_unit: bool = False
    conversion_to_base: Decimal = Field(gt=0)
    allow_decimal_quantity: bool = True
    rounding_precision: Decimal = Field(default=Decimal("0.000001"), gt=0)
    requires_measured_quantity: bool = False
    is_active: bool = True


class VariantUnitUpdate(RequestSchema):
    product_variant_id: uuid.UUID | None = None
    unit_id: uuid.UUID | None = None
    is_base_unit: bool | None = None
    is_purchase_unit: bool | None = None
    is_sales_unit: bool | None = None
    conversion_to_base: Decimal | None = Field(default=None, gt=0)
    allow_decimal_quantity: bool | None = None
    rounding_precision: Decimal | None = Field(default=None, gt=0)
    requires_measured_quantity: bool | None = None
    is_active: bool | None = None


class VariantBarcodeCreate(RequestSchema):
    product_variant_id: uuid.UUID
    variant_unit_id: uuid.UUID | None = None
    barcode: str = Field(min_length=1, max_length=120)
    is_primary: bool = False
    is_active: bool = True


class VariantBarcodeUpdate(RequestSchema):
    product_variant_id: uuid.UUID | None = None
    variant_unit_id: uuid.UUID | None = None
    barcode: str | None = Field(default=None, min_length=1, max_length=120)
    is_primary: bool | None = None
    is_active: bool | None = None


class VariantPosProfileCreate(RequestSchema):
    product_variant_id: uuid.UUID
    label: str | None = Field(default=None, min_length=1, max_length=80)
    color: str | None = Field(default=None, min_length=1, max_length=20)
    shape: PosTileShape = PosTileShape.SQUARE
    image_url: str | None = Field(default=None, min_length=1, max_length=500)
    sort_order: int = 0
    is_visible: bool = True


class VariantPosProfileUpdate(RequestSchema):
    product_variant_id: uuid.UUID | None = None
    label: str | None = Field(default=None, min_length=1, max_length=80)
    color: str | None = Field(default=None, min_length=1, max_length=20)
    shape: PosTileShape | None = None
    image_url: str | None = Field(default=None, min_length=1, max_length=500)
    sort_order: int | None = None
    is_visible: bool | None = None


class VariantLocationSettingCreate(RequestSchema):
    product_variant_id: uuid.UUID
    location_id: uuid.UUID
    is_available: bool = True
    low_stock_quantity_base: Decimal | None = Field(default=None, ge=0)
    preferred_supplier_id: uuid.UUID | None = None


class VariantLocationSettingUpdate(RequestSchema):
    product_variant_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None
    is_available: bool | None = None
    low_stock_quantity_base: Decimal | None = Field(default=None, ge=0)
    preferred_supplier_id: uuid.UUID | None = None


class CatalogItemOptionGroupCreate(RequestSchema):
    catalog_item_id: uuid.UUID
    name: str = Field(min_length=1, max_length=120)
    position: int = 0


class CatalogItemOptionGroupUpdate(RequestSchema):
    catalog_item_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    position: int | None = None


class CatalogItemOptionValueCreate(RequestSchema):
    option_group_id: uuid.UUID
    value: str = Field(min_length=1, max_length=120)
    position: int = 0


class CatalogItemOptionValueUpdate(RequestSchema):
    option_group_id: uuid.UUID | None = None
    value: str | None = Field(default=None, min_length=1, max_length=120)
    position: int | None = None


class ProductVariantOptionValueCreate(RequestSchema):
    product_variant_id: uuid.UUID
    option_value_id: uuid.UUID


class ProductVariantOptionValueUpdate(RequestSchema):
    product_variant_id: uuid.UUID | None = None
    option_value_id: uuid.UUID | None = None
