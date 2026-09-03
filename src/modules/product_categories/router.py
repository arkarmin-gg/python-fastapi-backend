import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from src.dependencies import DbSession
from src.exceptions import InvalidToken
from src.modules.auth.dependencies import CurrentUser
from src.modules.auth.exceptions import InactiveUser
from src.modules.product_categories import service
from src.modules.product_categories.exceptions import (
    InvalidParentProductCategory,
    ProductCategoryCodeConflict,
    ProductCategoryNotFound,
)
from src.modules.product_categories.schemas import (
    ProductCategoryCreate,
    ProductCategoryFilters,
    ProductCategoryListResponse,
    ProductCategoryRead,
    ProductCategoryUpdate,
    product_category_filters,
)
from src.modules.rbac.dependencies import require_permission
from src.modules.rbac.exceptions import PermissionDenied
from src.pagination import PaginationParams, pagination_params
from src.query_filters import SortSpec, parse_sort
from src.schemas import error_responses

router = APIRouter(prefix="/product-categories", tags=["Product Categories"])

SORT_FIELDS = {"code", "name", "created_at", "id"}
DEFAULT_SORT = ("name", "id")
AUTH_ERRORS = (InvalidToken, InactiveUser, PermissionDenied)


def product_category_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(sort, allowed_fields=SORT_FIELDS, default=DEFAULT_SORT)


@router.get(
    "",
    response_model=ProductCategoryListResponse,
    dependencies=[Depends(require_permission("product_categories.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_product_categories(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[ProductCategoryFilters, Depends(product_category_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(product_category_sort)],
):
    return await service.list_product_categories(db, current.tenant_id, pagination, filters, sort)


@router.post(
    "",
    response_model=ProductCategoryRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("product_categories.create"))],
    responses=error_responses(
        *AUTH_ERRORS, ProductCategoryCodeConflict, InvalidParentProductCategory
    ),
)
async def create_product_category(
    db: DbSession,
    current: CurrentUser,
    body: ProductCategoryCreate,
):
    return await service.create(db, current.tenant_id, body, actor_user_id=current.user_id)


@router.get(
    "/{product_category_id}",
    response_model=ProductCategoryRead,
    dependencies=[Depends(require_permission("product_categories.read"))],
    responses=error_responses(*AUTH_ERRORS, ProductCategoryNotFound),
)
async def get_product_category(
    db: DbSession,
    current: CurrentUser,
    product_category_id: uuid.UUID,
):
    category = await service.get_by_id(db, current.tenant_id, product_category_id)
    if category is None:
        raise ProductCategoryNotFound()
    return category


@router.patch(
    "/{product_category_id}",
    response_model=ProductCategoryRead,
    dependencies=[Depends(require_permission("product_categories.update"))],
    responses=error_responses(
        *AUTH_ERRORS,
        ProductCategoryNotFound,
        ProductCategoryCodeConflict,
        InvalidParentProductCategory,
    ),
)
async def update_product_category(
    db: DbSession,
    current: CurrentUser,
    product_category_id: uuid.UUID,
    body: ProductCategoryUpdate,
):
    return await service.update(
        db,
        current.tenant_id,
        product_category_id,
        body,
        actor_user_id=current.user_id,
    )


@router.delete(
    "/{product_category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("product_categories.delete"))],
    responses=error_responses(*AUTH_ERRORS, ProductCategoryNotFound),
)
async def deactivate_product_category(
    db: DbSession,
    current: CurrentUser,
    product_category_id: uuid.UUID,
) -> None:
    await service.deactivate(
        db, current.tenant_id, product_category_id, actor_user_id=current.user_id
    )
