import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile, status

from src.dependencies import DbSession
from src.exceptions import InvalidToken
from src.modules.auth.dependencies import CurrentUser
from src.modules.auth.exceptions import InactiveUser
from src.modules.catalog import service
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
    VariantUnitNotFound,
)
from src.modules.catalog.schemas import (
    BarcodeLookupRead,
    CatalogItemCreate,
    CatalogItemDetailRead,
    CatalogItemFilters,
    CatalogItemListResponse,
    CatalogItemOptionGroupCreate,
    CatalogItemOptionGroupDetailRead,
    CatalogItemOptionGroupFilters,
    CatalogItemOptionGroupListResponse,
    CatalogItemOptionGroupRead,
    CatalogItemOptionGroupUpdate,
    CatalogItemOptionValueCreate,
    CatalogItemOptionValueFilters,
    CatalogItemOptionValueListResponse,
    CatalogItemOptionValueRead,
    CatalogItemOptionValueUpdate,
    CatalogItemRead,
    CatalogItemUpdate,
    ProductVariantCreate,
    ProductVariantFilters,
    ProductVariantListResponse,
    ProductVariantOptionValueCreate,
    ProductVariantOptionValueFilters,
    ProductVariantOptionValueListResponse,
    ProductVariantOptionValueRead,
    ProductVariantOptionValueUpdate,
    ProductVariantRead,
    ProductVariantUpdate,
    VariantBarcodeCreate,
    VariantBarcodeFilters,
    VariantBarcodeListResponse,
    VariantBarcodeRead,
    VariantBarcodeUpdate,
    VariantLocationSettingCreate,
    VariantLocationSettingFilters,
    VariantLocationSettingListResponse,
    VariantLocationSettingRead,
    VariantLocationSettingUpdate,
    VariantPosProfileCreate,
    VariantPosProfileFilters,
    VariantPosProfileListResponse,
    VariantPosProfileRead,
    VariantPosProfileUpdate,
    VariantUnitCreate,
    VariantUnitFilters,
    VariantUnitListResponse,
    VariantUnitRead,
    VariantUnitUpdate,
    catalog_item_filters,
    catalog_item_option_group_filters,
    catalog_item_option_value_filters,
    product_variant_filters,
    product_variant_option_value_filters,
    variant_barcode_filters,
    variant_location_setting_filters,
    variant_pos_profile_filters,
    variant_unit_filters,
)
from src.modules.rbac.dependencies import require_permission
from src.modules.rbac.exceptions import PermissionDenied
from src.pagination import PaginationParams, pagination_params
from src.query_filters import SortSpec, parse_sort
from src.schemas import error_responses
from src.storage.exceptions import (
    FileTooLarge,
    StorageError,
    StorageNotConfigured,
    UnsupportedFileType,
)

router = APIRouter(tags=["Catalog"])

AUTH_ERRORS = (InvalidToken, InactiveUser, PermissionDenied)
CATALOG_ITEM_ERRORS = (InvalidCatalogCategory,)
VARIANT_ERRORS = (ProductVariantSkuConflict, InvalidCatalogItem, InvalidCatalogUnit)
VARIANT_UNIT_ERRORS = (
    VariantUnitConflict,
    VariantUnitBaseConflict,
    InvalidCatalogUnit,
    InvalidVariantBaseUnit,
    ProductVariantNotFound,
)
BARCODE_ERRORS = (
    VariantBarcodeConflict,
    VariantPrimaryBarcodeConflict,
    ProductVariantNotFound,
    InvalidVariantUnit,
)
POS_PROFILE_ERRORS = (VariantPosProfileConflict, ProductVariantNotFound)
LOCATION_SETTING_ERRORS = (
    VariantLocationSettingConflict,
    ProductVariantNotFound,
    InvalidCatalogLocation,
    InvalidCatalogSupplier,
)
CATALOG_ITEM_IMAGE_ERRORS = (
    CatalogItemNotFound,
    UnsupportedFileType,
    FileTooLarge,
    StorageNotConfigured,
    StorageError,
)
OPTION_GROUP_ERRORS = (
    CatalogItemOptionGroupConflict,
    InvalidCatalogItem,
)
OPTION_VALUE_ERRORS = (
    CatalogItemOptionValueConflict,
    InvalidCatalogItemOptionGroup,
)
VARIANT_OPTION_VALUE_ERRORS = (
    ProductVariantOptionValueConflict,
    ProductVariantOptionGroupConflict,
    ProductVariantNotFound,
    InvalidCatalogItemOptionValue,
    InvalidProductVariantOptionValue,
)


def catalog_item_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(
        sort,
        allowed_fields={"code", "name", "item_kind", "created_at", "id"},
        default=("code", "id"),
    )


def product_variant_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(
        sort,
        allowed_fields={"sku", "name", "created_at", "id"},
        default=("sku", "id"),
    )


def variant_unit_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(
        sort,
        allowed_fields={"product_variant_id", "unit_id", "conversion_to_base", "id"},
        default=("product_variant_id", "unit_id", "id"),
    )


def variant_barcode_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(
        sort,
        allowed_fields={"barcode", "product_variant_id", "id"},
        default=("barcode", "id"),
    )


def variant_pos_profile_sort(
    sort: Annotated[str | None, Query()] = None,
) -> tuple[SortSpec, ...]:
    return parse_sort(
        sort,
        allowed_fields={"sort_order", "product_variant_id", "id"},
        default=("sort_order", "id"),
    )


def variant_location_setting_sort(
    sort: Annotated[str | None, Query()] = None,
) -> tuple[SortSpec, ...]:
    return parse_sort(
        sort,
        allowed_fields={"product_variant_id", "location_id", "id"},
        default=("product_variant_id", "location_id", "id"),
    )


def option_group_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(
        sort,
        allowed_fields={"catalog_item_id", "name", "position", "id"},
        default=("catalog_item_id", "position", "id"),
    )


def option_value_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(
        sort,
        allowed_fields={"option_group_id", "value", "position", "id"},
        default=("option_group_id", "position", "id"),
    )


def variant_option_value_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(
        sort,
        allowed_fields={"product_variant_id", "option_value_id", "id"},
        default=("product_variant_id", "option_value_id", "id"),
    )


@router.get(
    "/catalog/barcode-lookup",
    response_model=BarcodeLookupRead,
    dependencies=[Depends(require_permission("catalog.read"))],
    responses=error_responses(*AUTH_ERRORS, VariantBarcodeNotFound),
)
async def lookup_barcode(
    db: DbSession,
    current: CurrentUser,
    barcode: Annotated[str, Query(min_length=1, max_length=120)],
):
    return await service.lookup_barcode(db, current.tenant_id, barcode)


@router.get(
    "/catalog-items",
    response_model=CatalogItemListResponse,
    dependencies=[Depends(require_permission("catalog.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_catalog_items(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[CatalogItemFilters, Depends(catalog_item_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(catalog_item_sort)],
):
    return await service.list_catalog_items(db, current.tenant_id, pagination, filters, sort)


@router.post(
    "/catalog-items",
    response_model=CatalogItemDetailRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("catalog.create"))],
    responses=error_responses(
        *AUTH_ERRORS,
        *CATALOG_ITEM_ERRORS,
        *VARIANT_ERRORS,
        *BARCODE_ERRORS,
        *POS_PROFILE_ERRORS,
        *LOCATION_SETTING_ERRORS,
    ),
)
async def create_catalog_item(
    db: DbSession,
    current: CurrentUser,
    body: CatalogItemCreate,
):
    return await service.create_catalog_item(
        db, current.tenant_id, body, actor_user_id=current.user_id
    )


@router.get(
    "/catalog-items/{catalog_item_id}/detail",
    response_model=CatalogItemDetailRead,
    dependencies=[Depends(require_permission("catalog.read"))],
    responses=error_responses(*AUTH_ERRORS, CatalogItemNotFound),
)
async def get_catalog_item_detail(
    db: DbSession,
    current: CurrentUser,
    catalog_item_id: uuid.UUID,
):
    item = await service.get_catalog_item_detail_by_id(db, current.tenant_id, catalog_item_id)
    if item is None:
        raise CatalogItemNotFound()
    return item


@router.get(
    "/catalog-items/{catalog_item_id}",
    response_model=CatalogItemRead,
    dependencies=[Depends(require_permission("catalog.read"))],
    responses=error_responses(*AUTH_ERRORS, CatalogItemNotFound),
)
async def get_catalog_item(
    db: DbSession,
    current: CurrentUser,
    catalog_item_id: uuid.UUID,
):
    item = await service.get_catalog_item_by_id(db, current.tenant_id, catalog_item_id)
    if item is None:
        raise CatalogItemNotFound()
    return item


@router.patch(
    "/catalog-items/{catalog_item_id}",
    response_model=CatalogItemRead,
    dependencies=[Depends(require_permission("catalog.update"))],
    responses=error_responses(*AUTH_ERRORS, CatalogItemNotFound, *CATALOG_ITEM_ERRORS),
)
async def update_catalog_item(
    db: DbSession,
    current: CurrentUser,
    catalog_item_id: uuid.UUID,
    body: CatalogItemUpdate,
):
    return await service.update_catalog_item(
        db,
        current.tenant_id,
        catalog_item_id,
        body,
        actor_user_id=current.user_id,
    )


@router.delete(
    "/catalog-items/{catalog_item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("catalog.delete"))],
    responses=error_responses(*AUTH_ERRORS, CatalogItemNotFound),
)
async def deactivate_catalog_item(
    db: DbSession,
    current: CurrentUser,
    catalog_item_id: uuid.UUID,
) -> None:
    await service.deactivate_catalog_item(
        db, current.tenant_id, catalog_item_id, actor_user_id=current.user_id
    )


@router.put(
    "/catalog-items/{catalog_item_id}/image",
    response_model=CatalogItemRead,
    dependencies=[Depends(require_permission("catalog.update"))],
    responses=error_responses(*AUTH_ERRORS, *CATALOG_ITEM_IMAGE_ERRORS),
)
async def upload_catalog_item_image(
    db: DbSession,
    current: CurrentUser,
    catalog_item_id: uuid.UUID,
    image: Annotated[UploadFile, File()],
):
    return await service.upload_catalog_item_image(
        db, current.tenant_id, catalog_item_id, image, actor_user_id=current.user_id
    )


@router.delete(
    "/catalog-items/{catalog_item_id}/image",
    response_model=CatalogItemRead,
    dependencies=[Depends(require_permission("catalog.update"))],
    responses=error_responses(*AUTH_ERRORS, CatalogItemNotFound),
)
async def delete_catalog_item_image(
    db: DbSession,
    current: CurrentUser,
    catalog_item_id: uuid.UUID,
):
    return await service.delete_catalog_item_image(
        db, current.tenant_id, catalog_item_id, actor_user_id=current.user_id
    )


@router.get(
    "/catalog-item-option-groups",
    response_model=CatalogItemOptionGroupListResponse,
    dependencies=[Depends(require_permission("catalog.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_catalog_item_option_groups(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[CatalogItemOptionGroupFilters, Depends(catalog_item_option_group_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(option_group_sort)],
):
    return await service.list_option_groups(db, current.tenant_id, pagination, filters, sort)


@router.post(
    "/catalog-item-option-groups",
    response_model=CatalogItemOptionGroupRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("catalog.create"))],
    responses=error_responses(*AUTH_ERRORS, *OPTION_GROUP_ERRORS),
)
async def create_catalog_item_option_group(
    db: DbSession,
    current: CurrentUser,
    body: CatalogItemOptionGroupCreate,
):
    return await service.create_option_group(
        db, current.tenant_id, body, actor_user_id=current.user_id
    )


@router.get(
    "/catalog-item-option-groups/{option_group_id}/detail",
    response_model=CatalogItemOptionGroupDetailRead,
    dependencies=[Depends(require_permission("catalog.read"))],
    responses=error_responses(*AUTH_ERRORS, CatalogItemOptionGroupNotFound),
)
async def get_catalog_item_option_group_detail(
    db: DbSession,
    current: CurrentUser,
    option_group_id: uuid.UUID,
):
    group = await service.get_option_group_detail_by_id(
        db,
        current.tenant_id,
        option_group_id,
    )
    if group is None:
        raise CatalogItemOptionGroupNotFound()
    return group


@router.get(
    "/catalog-item-option-groups/{option_group_id}",
    response_model=CatalogItemOptionGroupRead,
    dependencies=[Depends(require_permission("catalog.read"))],
    responses=error_responses(*AUTH_ERRORS, CatalogItemOptionGroupNotFound),
)
async def get_catalog_item_option_group(
    db: DbSession,
    current: CurrentUser,
    option_group_id: uuid.UUID,
):
    group = await service.get_option_group_by_id(db, current.tenant_id, option_group_id)
    if group is None:
        raise CatalogItemOptionGroupNotFound()
    return group


@router.patch(
    "/catalog-item-option-groups/{option_group_id}",
    response_model=CatalogItemOptionGroupRead,
    dependencies=[Depends(require_permission("catalog.update"))],
    responses=error_responses(
        *AUTH_ERRORS,
        CatalogItemOptionGroupNotFound,
        *OPTION_GROUP_ERRORS,
    ),
)
async def update_catalog_item_option_group(
    db: DbSession,
    current: CurrentUser,
    option_group_id: uuid.UUID,
    body: CatalogItemOptionGroupUpdate,
):
    return await service.update_option_group(
        db,
        current.tenant_id,
        option_group_id,
        body,
        actor_user_id=current.user_id,
    )


@router.delete(
    "/catalog-item-option-groups/{option_group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("catalog.delete"))],
    responses=error_responses(*AUTH_ERRORS, CatalogItemOptionGroupNotFound),
)
async def delete_catalog_item_option_group(
    db: DbSession,
    current: CurrentUser,
    option_group_id: uuid.UUID,
) -> None:
    await service.delete_option_group(
        db,
        current.tenant_id,
        option_group_id,
        actor_user_id=current.user_id,
    )


@router.get(
    "/catalog-item-option-values",
    response_model=CatalogItemOptionValueListResponse,
    dependencies=[Depends(require_permission("catalog.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_catalog_item_option_values(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[CatalogItemOptionValueFilters, Depends(catalog_item_option_value_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(option_value_sort)],
):
    return await service.list_option_values(db, current.tenant_id, pagination, filters, sort)


@router.post(
    "/catalog-item-option-values",
    response_model=CatalogItemOptionValueRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("catalog.create"))],
    responses=error_responses(*AUTH_ERRORS, *OPTION_VALUE_ERRORS),
)
async def create_catalog_item_option_value(
    db: DbSession,
    current: CurrentUser,
    body: CatalogItemOptionValueCreate,
):
    return await service.create_option_value(
        db, current.tenant_id, body, actor_user_id=current.user_id
    )


@router.get(
    "/catalog-item-option-values/{option_value_id}",
    response_model=CatalogItemOptionValueRead,
    dependencies=[Depends(require_permission("catalog.read"))],
    responses=error_responses(*AUTH_ERRORS, CatalogItemOptionValueNotFound),
)
async def get_catalog_item_option_value(
    db: DbSession,
    current: CurrentUser,
    option_value_id: uuid.UUID,
):
    value = await service.get_option_value_by_id(db, current.tenant_id, option_value_id)
    if value is None:
        raise CatalogItemOptionValueNotFound()
    return value


@router.patch(
    "/catalog-item-option-values/{option_value_id}",
    response_model=CatalogItemOptionValueRead,
    dependencies=[Depends(require_permission("catalog.update"))],
    responses=error_responses(
        *AUTH_ERRORS,
        CatalogItemOptionValueNotFound,
        *OPTION_VALUE_ERRORS,
    ),
)
async def update_catalog_item_option_value(
    db: DbSession,
    current: CurrentUser,
    option_value_id: uuid.UUID,
    body: CatalogItemOptionValueUpdate,
):
    return await service.update_option_value(
        db,
        current.tenant_id,
        option_value_id,
        body,
        actor_user_id=current.user_id,
    )


@router.delete(
    "/catalog-item-option-values/{option_value_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("catalog.delete"))],
    responses=error_responses(*AUTH_ERRORS, CatalogItemOptionValueNotFound),
)
async def delete_catalog_item_option_value(
    db: DbSession,
    current: CurrentUser,
    option_value_id: uuid.UUID,
) -> None:
    await service.delete_option_value(
        db,
        current.tenant_id,
        option_value_id,
        actor_user_id=current.user_id,
    )


@router.get(
    "/product-variants",
    response_model=ProductVariantListResponse,
    dependencies=[Depends(require_permission("catalog.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_product_variants(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[ProductVariantFilters, Depends(product_variant_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(product_variant_sort)],
):
    return await service.list_product_variants(db, current.tenant_id, pagination, filters, sort)


@router.post(
    "/product-variants",
    response_model=ProductVariantRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("catalog.create"))],
    responses=error_responses(*AUTH_ERRORS, *VARIANT_ERRORS, VariantUnitBaseConflict),
)
async def create_product_variant(
    db: DbSession,
    current: CurrentUser,
    body: ProductVariantCreate,
):
    return await service.create_product_variant(
        db, current.tenant_id, body, actor_user_id=current.user_id
    )


@router.get(
    "/product-variants/{product_variant_id}",
    response_model=ProductVariantRead,
    dependencies=[Depends(require_permission("catalog.read"))],
    responses=error_responses(*AUTH_ERRORS, ProductVariantNotFound),
)
async def get_product_variant(
    db: DbSession,
    current: CurrentUser,
    product_variant_id: uuid.UUID,
):
    variant = await service.get_product_variant_by_id(db, current.tenant_id, product_variant_id)
    if variant is None:
        raise ProductVariantNotFound()
    return variant


@router.patch(
    "/product-variants/{product_variant_id}",
    response_model=ProductVariantRead,
    dependencies=[Depends(require_permission("catalog.update"))],
    responses=error_responses(*AUTH_ERRORS, ProductVariantNotFound, *VARIANT_ERRORS),
)
async def update_product_variant(
    db: DbSession,
    current: CurrentUser,
    product_variant_id: uuid.UUID,
    body: ProductVariantUpdate,
):
    return await service.update_product_variant(
        db,
        current.tenant_id,
        product_variant_id,
        body,
        actor_user_id=current.user_id,
    )


@router.delete(
    "/product-variants/{product_variant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("catalog.delete"))],
    responses=error_responses(*AUTH_ERRORS, ProductVariantNotFound),
)
async def deactivate_product_variant(
    db: DbSession,
    current: CurrentUser,
    product_variant_id: uuid.UUID,
) -> None:
    await service.deactivate_product_variant(
        db, current.tenant_id, product_variant_id, actor_user_id=current.user_id
    )


@router.get(
    "/product-variant-option-values",
    response_model=ProductVariantOptionValueListResponse,
    dependencies=[Depends(require_permission("catalog.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_product_variant_option_values(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[
        ProductVariantOptionValueFilters,
        Depends(product_variant_option_value_filters),
    ],
    sort: Annotated[tuple[SortSpec, ...], Depends(variant_option_value_sort)],
):
    return await service.list_variant_option_values(
        db,
        current.tenant_id,
        pagination,
        filters,
        sort,
    )


@router.post(
    "/product-variant-option-values",
    response_model=ProductVariantOptionValueRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("catalog.create"))],
    responses=error_responses(*AUTH_ERRORS, *VARIANT_OPTION_VALUE_ERRORS),
)
async def create_product_variant_option_value(
    db: DbSession,
    current: CurrentUser,
    body: ProductVariantOptionValueCreate,
):
    return await service.create_variant_option_value(
        db,
        current.tenant_id,
        body,
        actor_user_id=current.user_id,
    )


@router.get(
    "/product-variant-option-values/{link_id}",
    response_model=ProductVariantOptionValueRead,
    dependencies=[Depends(require_permission("catalog.read"))],
    responses=error_responses(*AUTH_ERRORS, ProductVariantOptionValueNotFound),
)
async def get_product_variant_option_value(
    db: DbSession,
    current: CurrentUser,
    link_id: uuid.UUID,
):
    link = await service.get_variant_option_value_by_id(db, current.tenant_id, link_id)
    if link is None:
        raise ProductVariantOptionValueNotFound()
    return link


@router.patch(
    "/product-variant-option-values/{link_id}",
    response_model=ProductVariantOptionValueRead,
    dependencies=[Depends(require_permission("catalog.update"))],
    responses=error_responses(
        *AUTH_ERRORS,
        ProductVariantOptionValueNotFound,
        *VARIANT_OPTION_VALUE_ERRORS,
    ),
)
async def update_product_variant_option_value(
    db: DbSession,
    current: CurrentUser,
    link_id: uuid.UUID,
    body: ProductVariantOptionValueUpdate,
):
    return await service.update_variant_option_value(
        db,
        current.tenant_id,
        link_id,
        body,
        actor_user_id=current.user_id,
    )


@router.delete(
    "/product-variant-option-values/{link_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("catalog.delete"))],
    responses=error_responses(*AUTH_ERRORS, ProductVariantOptionValueNotFound),
)
async def delete_product_variant_option_value(
    db: DbSession,
    current: CurrentUser,
    link_id: uuid.UUID,
) -> None:
    await service.delete_variant_option_value(
        db,
        current.tenant_id,
        link_id,
        actor_user_id=current.user_id,
    )


@router.get(
    "/variant-units",
    response_model=VariantUnitListResponse,
    dependencies=[Depends(require_permission("catalog.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_variant_units(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[VariantUnitFilters, Depends(variant_unit_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(variant_unit_sort)],
):
    return await service.list_variant_units(db, current.tenant_id, pagination, filters, sort)


@router.post(
    "/variant-units",
    response_model=VariantUnitRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("catalog.create"))],
    responses=error_responses(*AUTH_ERRORS, *VARIANT_UNIT_ERRORS),
)
async def create_variant_unit(
    db: DbSession,
    current: CurrentUser,
    body: VariantUnitCreate,
):
    return await service.create_variant_unit(
        db, current.tenant_id, body, actor_user_id=current.user_id
    )


@router.get(
    "/variant-units/{variant_unit_id}",
    response_model=VariantUnitRead,
    dependencies=[Depends(require_permission("catalog.read"))],
    responses=error_responses(*AUTH_ERRORS, VariantUnitNotFound),
)
async def get_variant_unit(
    db: DbSession,
    current: CurrentUser,
    variant_unit_id: uuid.UUID,
):
    variant_unit = await service.get_variant_unit_by_id(db, current.tenant_id, variant_unit_id)
    if variant_unit is None:
        raise VariantUnitNotFound()
    return variant_unit


@router.patch(
    "/variant-units/{variant_unit_id}",
    response_model=VariantUnitRead,
    dependencies=[Depends(require_permission("catalog.update"))],
    responses=error_responses(*AUTH_ERRORS, VariantUnitNotFound, *VARIANT_UNIT_ERRORS),
)
async def update_variant_unit(
    db: DbSession,
    current: CurrentUser,
    variant_unit_id: uuid.UUID,
    body: VariantUnitUpdate,
):
    return await service.update_variant_unit(
        db, current.tenant_id, variant_unit_id, body, actor_user_id=current.user_id
    )


@router.delete(
    "/variant-units/{variant_unit_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("catalog.delete"))],
    responses=error_responses(*AUTH_ERRORS, VariantUnitNotFound),
)
async def deactivate_variant_unit(
    db: DbSession,
    current: CurrentUser,
    variant_unit_id: uuid.UUID,
) -> None:
    await service.deactivate_variant_unit(
        db, current.tenant_id, variant_unit_id, actor_user_id=current.user_id
    )


@router.get(
    "/variant-barcodes",
    response_model=VariantBarcodeListResponse,
    dependencies=[Depends(require_permission("catalog.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_variant_barcodes(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[VariantBarcodeFilters, Depends(variant_barcode_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(variant_barcode_sort)],
):
    return await service.list_variant_barcodes(db, current.tenant_id, pagination, filters, sort)


@router.post(
    "/variant-barcodes",
    response_model=VariantBarcodeRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("catalog.create"))],
    responses=error_responses(*AUTH_ERRORS, *BARCODE_ERRORS),
)
async def create_variant_barcode(
    db: DbSession,
    current: CurrentUser,
    body: VariantBarcodeCreate,
):
    return await service.create_variant_barcode(
        db, current.tenant_id, body, actor_user_id=current.user_id
    )


@router.get(
    "/variant-barcodes/{variant_barcode_id}",
    response_model=VariantBarcodeRead,
    dependencies=[Depends(require_permission("catalog.read"))],
    responses=error_responses(*AUTH_ERRORS, VariantBarcodeNotFound),
)
async def get_variant_barcode(
    db: DbSession,
    current: CurrentUser,
    variant_barcode_id: uuid.UUID,
):
    barcode = await service.get_variant_barcode_by_id(
        db,
        current.tenant_id,
        variant_barcode_id,
    )
    if barcode is None:
        raise VariantBarcodeNotFound()
    return barcode


@router.patch(
    "/variant-barcodes/{variant_barcode_id}",
    response_model=VariantBarcodeRead,
    dependencies=[Depends(require_permission("catalog.update"))],
    responses=error_responses(*AUTH_ERRORS, VariantBarcodeNotFound, *BARCODE_ERRORS),
)
async def update_variant_barcode(
    db: DbSession,
    current: CurrentUser,
    variant_barcode_id: uuid.UUID,
    body: VariantBarcodeUpdate,
):
    return await service.update_variant_barcode(
        db, current.tenant_id, variant_barcode_id, body, actor_user_id=current.user_id
    )


@router.delete(
    "/variant-barcodes/{variant_barcode_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("catalog.delete"))],
    responses=error_responses(*AUTH_ERRORS, VariantBarcodeNotFound),
)
async def deactivate_variant_barcode(
    db: DbSession,
    current: CurrentUser,
    variant_barcode_id: uuid.UUID,
) -> None:
    await service.deactivate_variant_barcode(
        db, current.tenant_id, variant_barcode_id, actor_user_id=current.user_id
    )


@router.get(
    "/variant-pos-profiles",
    response_model=VariantPosProfileListResponse,
    dependencies=[Depends(require_permission("catalog.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_variant_pos_profiles(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[VariantPosProfileFilters, Depends(variant_pos_profile_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(variant_pos_profile_sort)],
):
    return await service.list_variant_pos_profiles(db, current.tenant_id, pagination, filters, sort)


@router.post(
    "/variant-pos-profiles",
    response_model=VariantPosProfileRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("catalog.create"))],
    responses=error_responses(*AUTH_ERRORS, *POS_PROFILE_ERRORS),
)
async def create_variant_pos_profile(
    db: DbSession,
    current: CurrentUser,
    body: VariantPosProfileCreate,
):
    return await service.create_variant_pos_profile(
        db, current.tenant_id, body, actor_user_id=current.user_id
    )


@router.get(
    "/variant-pos-profiles/{profile_id}",
    response_model=VariantPosProfileRead,
    dependencies=[Depends(require_permission("catalog.read"))],
    responses=error_responses(*AUTH_ERRORS, VariantPosProfileNotFound),
)
async def get_variant_pos_profile(
    db: DbSession,
    current: CurrentUser,
    profile_id: uuid.UUID,
):
    profile = await service.get_variant_pos_profile_by_id(db, current.tenant_id, profile_id)
    if profile is None:
        raise VariantPosProfileNotFound()
    return profile


@router.patch(
    "/variant-pos-profiles/{profile_id}",
    response_model=VariantPosProfileRead,
    dependencies=[Depends(require_permission("catalog.update"))],
    responses=error_responses(*AUTH_ERRORS, VariantPosProfileNotFound, *POS_PROFILE_ERRORS),
)
async def update_variant_pos_profile(
    db: DbSession,
    current: CurrentUser,
    profile_id: uuid.UUID,
    body: VariantPosProfileUpdate,
):
    return await service.update_variant_pos_profile(
        db, current.tenant_id, profile_id, body, actor_user_id=current.user_id
    )


@router.delete(
    "/variant-pos-profiles/{profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("catalog.delete"))],
    responses=error_responses(*AUTH_ERRORS, VariantPosProfileNotFound),
)
async def delete_variant_pos_profile(
    db: DbSession,
    current: CurrentUser,
    profile_id: uuid.UUID,
) -> None:
    await service.delete_variant_pos_profile(
        db,
        current.tenant_id,
        profile_id,
        actor_user_id=current.user_id,
    )


@router.get(
    "/variant-location-settings",
    response_model=VariantLocationSettingListResponse,
    dependencies=[Depends(require_permission("catalog.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_variant_location_settings(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[VariantLocationSettingFilters, Depends(variant_location_setting_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(variant_location_setting_sort)],
):
    return await service.list_variant_location_settings(
        db, current.tenant_id, pagination, filters, sort
    )


@router.post(
    "/variant-location-settings",
    response_model=VariantLocationSettingRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("catalog.create"))],
    responses=error_responses(*AUTH_ERRORS, *LOCATION_SETTING_ERRORS),
)
async def create_variant_location_setting(
    db: DbSession,
    current: CurrentUser,
    body: VariantLocationSettingCreate,
):
    return await service.create_variant_location_setting(
        db, current.tenant_id, body, actor_user_id=current.user_id
    )


@router.get(
    "/variant-location-settings/{setting_id}",
    response_model=VariantLocationSettingRead,
    dependencies=[Depends(require_permission("catalog.read"))],
    responses=error_responses(*AUTH_ERRORS, VariantLocationSettingNotFound),
)
async def get_variant_location_setting(
    db: DbSession,
    current: CurrentUser,
    setting_id: uuid.UUID,
):
    setting = await service.get_variant_location_setting_by_id(
        db,
        current.tenant_id,
        setting_id,
    )
    if setting is None:
        raise VariantLocationSettingNotFound()
    return setting


@router.patch(
    "/variant-location-settings/{setting_id}",
    response_model=VariantLocationSettingRead,
    dependencies=[Depends(require_permission("catalog.update"))],
    responses=error_responses(
        *AUTH_ERRORS,
        VariantLocationSettingNotFound,
        *LOCATION_SETTING_ERRORS,
    ),
)
async def update_variant_location_setting(
    db: DbSession,
    current: CurrentUser,
    setting_id: uuid.UUID,
    body: VariantLocationSettingUpdate,
):
    return await service.update_variant_location_setting(
        db, current.tenant_id, setting_id, body, actor_user_id=current.user_id
    )


@router.delete(
    "/variant-location-settings/{setting_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("catalog.delete"))],
    responses=error_responses(*AUTH_ERRORS, VariantLocationSettingNotFound),
)
async def delete_variant_location_setting(
    db: DbSession,
    current: CurrentUser,
    setting_id: uuid.UUID,
) -> None:
    await service.delete_variant_location_setting(
        db,
        current.tenant_id,
        setting_id,
        actor_user_id=current.user_id,
    )
