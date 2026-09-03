from fastapi import status

from src.exceptions import AppException, ConflictError, NotFoundError


class CatalogItemNotFound(NotFoundError):
    error_code = "catalog_item_not_found"
    detail = "Catalog item not found."


class ProductVariantNotFound(NotFoundError):
    error_code = "product_variant_not_found"
    detail = "Product variant not found."


class VariantUnitNotFound(NotFoundError):
    error_code = "variant_unit_not_found"
    detail = "Variant unit not found."


class VariantBarcodeNotFound(NotFoundError):
    error_code = "variant_barcode_not_found"
    detail = "Variant barcode not found."


class VariantPosProfileNotFound(NotFoundError):
    error_code = "variant_pos_profile_not_found"
    detail = "Variant POS profile not found."


class VariantLocationSettingNotFound(NotFoundError):
    error_code = "variant_location_setting_not_found"
    detail = "Variant location setting not found."


class CatalogItemOptionGroupNotFound(NotFoundError):
    error_code = "catalog_item_option_group_not_found"
    detail = "Catalog item option group not found."


class CatalogItemOptionValueNotFound(NotFoundError):
    error_code = "catalog_item_option_value_not_found"
    detail = "Catalog item option value not found."


class ProductVariantOptionValueNotFound(NotFoundError):
    error_code = "product_variant_option_value_not_found"
    detail = "Product variant option value link not found."


class ProductVariantSkuConflict(ConflictError):
    error_code = "product_variant_sku_conflict"
    detail = "A product variant with this SKU already exists for the tenant."


class VariantUnitConflict(ConflictError):
    error_code = "variant_unit_conflict"
    detail = "An active variant unit already exists for this variant and unit."


class VariantUnitBaseConflict(ConflictError):
    error_code = "variant_unit_base_conflict"
    detail = "An active base unit already exists for this variant."


class VariantUnitImmutable(ConflictError):
    error_code = "variant_unit_immutable"
    detail = (
        "A referenced variant unit cannot have its conversion or quantity rules changed. "
        "Create a new unit version instead."
    )


class VariantBarcodeConflict(ConflictError):
    error_code = "variant_barcode_conflict"
    detail = "An active barcode already exists for this tenant."


class VariantPrimaryBarcodeConflict(ConflictError):
    error_code = "variant_primary_barcode_conflict"
    detail = "An active primary barcode already exists for this variant."


class VariantPosProfileConflict(ConflictError):
    error_code = "variant_pos_profile_conflict"
    detail = "A POS profile already exists for this variant."


class VariantLocationSettingConflict(ConflictError):
    error_code = "variant_location_setting_conflict"
    detail = "Location settings already exist for this variant and location."


class CatalogItemOptionGroupConflict(ConflictError):
    error_code = "catalog_item_option_group_conflict"
    detail = "An option group with this name already exists for this catalog item."


class CatalogItemOptionValueConflict(ConflictError):
    error_code = "catalog_item_option_value_conflict"
    detail = "An option value already exists in this option group."


class ProductVariantOptionValueConflict(ConflictError):
    error_code = "product_variant_option_value_conflict"
    detail = "This option value is already linked to the product variant."


class ProductVariantOptionGroupConflict(ConflictError):
    error_code = "product_variant_option_group_conflict"
    detail = "This product variant already has an option value for the option group."


class InvalidCatalogCategory(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "invalid_catalog_category"
    detail = "Category must be active and belong to the tenant."


class InvalidCatalogItem(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "invalid_catalog_item"
    detail = "Catalog item must be active and belong to the tenant."


class InvalidCatalogItemOptionGroup(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "invalid_catalog_item_option_group"
    detail = "Option group must belong to an active catalog item in the tenant."


class InvalidCatalogItemOptionValue(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "invalid_catalog_item_option_value"
    detail = "Option value must belong to an active catalog item in the tenant."


class InvalidProductVariantOptionValue(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "invalid_product_variant_option_value"
    detail = "Option value must belong to the same catalog item as the product variant."


class InvalidCatalogUnit(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "invalid_catalog_unit"
    detail = "Unit must exist and be active."


class InvalidVariantUnit(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "invalid_variant_unit"
    detail = "Variant unit must be active and belong to the selected variant."


class InvalidVariantUnitKind(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "invalid_variant_unit_kind"
    detail = "A non-package unit must have the same measurement kind as the variant base unit."


class InvalidVariantBaseUnit(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "invalid_variant_base_unit"
    detail = "Base variant unit must match the variant base unit and use conversion value 1."


class InvalidCatalogLocation(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "invalid_catalog_location"
    detail = "Location must be active and belong to the tenant."


class InvalidCatalogSupplier(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "invalid_catalog_supplier"
    detail = "Preferred supplier must be active and belong to the tenant."
