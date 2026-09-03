import uuid
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy import update as sqlalchemy_update
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.audit_logs.service import record_audit_log
from src.modules.codes.service import generate_code
from src.modules.price_levels.exceptions import PriceLevelCodeConflict, PriceLevelNotFound
from src.modules.price_levels.models import PriceLevel
from src.modules.price_levels.schemas import PriceLevelCreate, PriceLevelFilters, PriceLevelUpdate
from src.pagination import Page, PaginationParams, paginate
from src.query_filters import SortSpec, apply_sort, search_clause

PRICE_LEVEL_SORT_COLUMNS = {
    "code": PriceLevel.code,
    "name": PriceLevel.name,
    "id": PriceLevel.id,
}


async def get_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    price_level_id: uuid.UUID,
) -> PriceLevel | None:
    return await db.scalar(
        select(PriceLevel).where(
            PriceLevel.tenant_id == tenant_id,
            PriceLevel.id == price_level_id,
        )
    )


async def list_price_levels(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: PriceLevelFilters,
    sort: tuple[SortSpec, ...],
) -> Page[PriceLevel]:
    stmt = _apply_filters(select(PriceLevel).where(PriceLevel.tenant_id == tenant_id), filters)
    stmt = apply_sort(stmt, sort, PRICE_LEVEL_SORT_COLUMNS)
    count_stmt = _apply_filters(
        select(func.count(PriceLevel.id)).where(PriceLevel.tenant_id == tenant_id),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def create(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: PriceLevelCreate,
    *,
    actor_user_id: uuid.UUID,
) -> PriceLevel:
    price_level = PriceLevel(
        tenant_id=tenant_id,
        code=await generate_code(db, tenant_id, "price_level"),
        **data.model_dump(),
    )
    db.add(price_level)
    await db.flush()
    _normalize_default_state(price_level)
    if price_level.is_default:
        await _clear_other_defaults(db, tenant_id, price_level.id)
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="price_levels.create",
        entity_type="price_level",
        entity_id=price_level.id,
        after_json=_loggable(price_level),
    )
    await db.commit()
    await db.refresh(price_level)
    return price_level


async def update(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    price_level_id: uuid.UUID,
    data: PriceLevelUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> PriceLevel:
    price_level = await get_by_id(db, tenant_id, price_level_id)
    if price_level is None:
        raise PriceLevelNotFound()
    before = _loggable(price_level)
    fields = data.model_dump(exclude_unset=True)
    for key, value in fields.items():
        setattr(price_level, key, value)
    await db.flush()
    _normalize_default_state(price_level)
    if price_level.is_default:
        await _clear_other_defaults(db, tenant_id, price_level.id)
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="price_levels.update",
        entity_type="price_level",
        entity_id=price_level.id,
        before_json=before,
        after_json=_loggable(price_level),
    )
    await db.commit()
    await db.refresh(price_level)
    return price_level


async def deactivate(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    price_level_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    price_level = await get_by_id(db, tenant_id, price_level_id)
    if price_level is None:
        raise PriceLevelNotFound()
    before = _loggable(price_level)
    price_level.is_active = False
    price_level.is_default = False
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="price_levels.deactivate",
        entity_type="price_level",
        entity_id=price_level.id,
        before_json=before,
        after_json=_loggable(price_level),
    )
    await db.commit()


async def _ensure_code_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    code: str,
    *,
    price_level_id: uuid.UUID | None = None,
) -> None:
    existing = await db.scalar(
        select(PriceLevel).where(
            PriceLevel.tenant_id == tenant_id,
            PriceLevel.code == code,
        )
    )
    if existing is not None and existing.id != price_level_id:
        raise PriceLevelCodeConflict()


async def _clear_other_defaults(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    price_level_id: uuid.UUID,
) -> None:
    await db.execute(
        sqlalchemy_update(PriceLevel)
        .where(
            PriceLevel.tenant_id == tenant_id,
            PriceLevel.id != price_level_id,
            PriceLevel.is_default.is_(True),
        )
        .values(is_default=False)
    )


def _apply_filters[StmtT: Select[Any]](stmt: StmtT, filters: PriceLevelFilters) -> StmtT:
    search = search_clause(
        [PriceLevel.code, PriceLevel.name, PriceLevel.description],
        filters.search,
    )
    if search is not None:
        stmt = stmt.where(search)
    if filters.is_default is not None:
        stmt = stmt.where(PriceLevel.is_default == filters.is_default)
    if filters.is_active is not None:
        stmt = stmt.where(PriceLevel.is_active == filters.is_active)
    return stmt


def _loggable(price_level: PriceLevel) -> dict[str, Any]:
    return {
        "code": price_level.code,
        "name": price_level.name,
        "description": price_level.description,
        "is_default": price_level.is_default,
        "is_active": price_level.is_active,
    }


def _normalize_default_state(price_level: PriceLevel) -> None:
    if not price_level.is_active:
        price_level.is_default = False
