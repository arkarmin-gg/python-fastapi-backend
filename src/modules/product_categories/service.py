import uuid
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.audit_logs.service import record_audit_log
from src.modules.codes.service import generate_code
from src.modules.product_categories.exceptions import (
    InvalidParentProductCategory,
    ProductCategoryCodeConflict,
    ProductCategoryNotFound,
)
from src.modules.product_categories.models import ProductCategory
from src.modules.product_categories.schemas import (
    ProductCategoryCreate,
    ProductCategoryFilters,
    ProductCategoryUpdate,
)
from src.pagination import Page, PaginationParams, paginate
from src.query_filters import SortSpec, apply_sort, search_clause

PRODUCT_CATEGORY_SORT_COLUMNS = {
    "code": ProductCategory.code,
    "name": ProductCategory.name,
    "created_at": ProductCategory.created_at,
    "id": ProductCategory.id,
}


async def get_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    product_category_id: uuid.UUID,
) -> ProductCategory | None:
    return await db.scalar(
        select(ProductCategory).where(
            ProductCategory.tenant_id == tenant_id,
            ProductCategory.id == product_category_id,
        )
    )


async def list_product_categories(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: ProductCategoryFilters,
    sort: tuple[SortSpec, ...],
) -> Page[ProductCategory]:
    stmt = _apply_filters(
        select(ProductCategory).where(ProductCategory.tenant_id == tenant_id), filters
    )
    stmt = apply_sort(stmt, sort, PRODUCT_CATEGORY_SORT_COLUMNS)
    count_stmt = _apply_filters(
        select(func.count(ProductCategory.id)).where(ProductCategory.tenant_id == tenant_id),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def create(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: ProductCategoryCreate,
    *,
    actor_user_id: uuid.UUID,
) -> ProductCategory:
    if data.parent_category_id is not None:
        await _ensure_parent_exists(db, tenant_id, data.parent_category_id)
    category = ProductCategory(
        tenant_id=tenant_id,
        code=await generate_code(db, tenant_id, "product_category"),
        **data.model_dump(),
    )
    db.add(category)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="product_categories.create",
        entity_type="product_category",
        entity_id=category.id,
        after_json=_loggable(category),
    )
    await db.commit()
    await db.refresh(category)
    return category


async def update(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    product_category_id: uuid.UUID,
    data: ProductCategoryUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> ProductCategory:
    category = await get_by_id(db, tenant_id, product_category_id)
    if category is None:
        raise ProductCategoryNotFound()
    before = _loggable(category)
    fields = data.model_dump(exclude_unset=True)
    if "parent_category_id" in fields:
        await _ensure_valid_parent(
            db,
            tenant_id,
            category.id,
            fields["parent_category_id"],
        )
    for key, value in fields.items():
        setattr(category, key, value)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="product_categories.update",
        entity_type="product_category",
        entity_id=category.id,
        before_json=before,
        after_json=_loggable(category),
    )
    await db.commit()
    await db.refresh(category)
    return category


async def deactivate(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    product_category_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    category = await get_by_id(db, tenant_id, product_category_id)
    if category is None:
        raise ProductCategoryNotFound()
    before = _loggable(category)
    category.is_active = False
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="product_categories.deactivate",
        entity_type="product_category",
        entity_id=category.id,
        before_json=before,
        after_json=_loggable(category),
    )
    await db.commit()


async def _ensure_code_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    code: str | None,
    *,
    product_category_id: uuid.UUID | None = None,
) -> None:
    if code is None:
        return
    existing = await db.scalar(
        select(ProductCategory).where(
            ProductCategory.tenant_id == tenant_id,
            ProductCategory.code == code,
        )
    )
    if existing is not None and existing.id != product_category_id:
        raise ProductCategoryCodeConflict()


async def _ensure_parent_exists(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    parent_category_id: uuid.UUID,
) -> ProductCategory:
    parent = await get_by_id(db, tenant_id, parent_category_id)
    if parent is None:
        raise InvalidParentProductCategory()
    return parent


async def _ensure_valid_parent(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    category_id: uuid.UUID,
    parent_category_id: uuid.UUID | None,
) -> None:
    if parent_category_id is None:
        return
    if parent_category_id == category_id:
        raise InvalidParentProductCategory()
    parent = await _ensure_parent_exists(db, tenant_id, parent_category_id)
    while parent.parent_category_id is not None:
        if parent.parent_category_id == category_id:
            raise InvalidParentProductCategory()
        parent = await _ensure_parent_exists(db, tenant_id, parent.parent_category_id)


def _apply_filters[StmtT: Select[Any]](stmt: StmtT, filters: ProductCategoryFilters) -> StmtT:
    search = search_clause(
        [ProductCategory.code, ProductCategory.name, ProductCategory.description],
        filters.search,
    )
    if search is not None:
        stmt = stmt.where(search)
    if filters.parent_category_id is not None:
        stmt = stmt.where(ProductCategory.parent_category_id == filters.parent_category_id)
    if filters.is_active is not None:
        stmt = stmt.where(ProductCategory.is_active == filters.is_active)
    return stmt


def _loggable(category: ProductCategory) -> dict[str, Any]:
    return {
        "parent_category_id": str(category.parent_category_id)
        if category.parent_category_id is not None
        else None,
        "code": category.code,
        "name": category.name,
        "description": category.description,
        "is_active": category.is_active,
    }
