import uuid
from typing import Any

from sqlalchemy import Select, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.audit_logs.service import record_audit_log
from src.modules.catalog.models import ProductVariant, VariantUnit
from src.modules.units.exceptions import UnitCodeConflict, UnitInUse, UnitNotFound
from src.modules.units.models import Unit
from src.modules.units.schemas import UnitCreate, UnitFilters, UnitUpdate
from src.pagination import Page, PaginationParams, paginate
from src.query_filters import SortSpec, apply_sort, search_clause

UNIT_SORT_COLUMNS = {
    "code": Unit.code,
    "name_en": Unit.name_en,
    "unit_kind": Unit.unit_kind,
    "id": Unit.id,
}


async def get_by_id(db: AsyncSession, unit_id: uuid.UUID) -> Unit | None:
    return await db.scalar(select(Unit).where(Unit.id == unit_id))


async def list_units(
    db: AsyncSession,
    pagination: PaginationParams,
    filters: UnitFilters,
    sort: tuple[SortSpec, ...],
) -> Page[Unit]:
    stmt = _apply_filters(select(Unit), filters)
    stmt = apply_sort(stmt, sort, UNIT_SORT_COLUMNS)
    count_stmt = _apply_filters(select(func.count(Unit.id)), filters)
    return await paginate(db, stmt, count_stmt, pagination)


async def create(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: UnitCreate,
    *,
    actor_user_id: uuid.UUID,
) -> Unit:
    await _ensure_code_available(db, data.code)
    unit = Unit(**data.model_dump())
    db.add(unit)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="units.create",
        entity_type="unit",
        entity_id=unit.id,
        after_json=_loggable(unit),
    )
    await db.commit()
    await db.refresh(unit)
    return unit


async def update(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    unit_id: uuid.UUID,
    data: UnitUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> Unit:
    unit = await get_by_id(db, unit_id)
    if unit is None:
        raise UnitNotFound()
    before = _loggable(unit)
    fields = data.model_dump(exclude_unset=True)
    new_code = fields.get("code")
    if new_code is not None and new_code != unit.code:
        await _ensure_code_available(db, new_code, unit_id=unit.id)
    await _ensure_mutable_if_referenced(db, unit, fields)
    for key, value in fields.items():
        setattr(unit, key, value)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="units.update",
        entity_type="unit",
        entity_id=unit.id,
        before_json=before,
        after_json=_loggable(unit),
    )
    await db.commit()
    await db.refresh(unit)
    return unit


async def deactivate(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    unit_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    unit = await get_by_id(db, unit_id)
    if unit is None:
        raise UnitNotFound()
    await _ensure_mutable_if_referenced(db, unit, {"is_active": False})
    before = _loggable(unit)
    unit.is_active = False
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="units.deactivate",
        entity_type="unit",
        entity_id=unit.id,
        before_json=before,
        after_json=_loggable(unit),
    )
    await db.commit()


async def _ensure_code_available(
    db: AsyncSession,
    code: str,
    *,
    unit_id: uuid.UUID | None = None,
) -> None:
    existing = await db.scalar(select(Unit).where(Unit.code == code))
    if existing is not None and existing.id != unit_id:
        raise UnitCodeConflict()


async def _ensure_mutable_if_referenced(
    db: AsyncSession,
    unit: Unit,
    fields: dict[str, Any],
) -> None:
    protected_fields = {"code", "unit_kind", "is_active"}
    if not protected_fields.intersection(fields):
        return
    referenced = await db.scalar(
        select(
            or_(
                exists().where(ProductVariant.base_unit_id == unit.id),
                exists().where(VariantUnit.unit_id == unit.id),
            )
        )
    )
    if referenced:
        raise UnitInUse()


def _apply_filters[StmtT: Select[Any]](stmt: StmtT, filters: UnitFilters) -> StmtT:
    search = search_clause([Unit.code, Unit.name_en, Unit.name_my], filters.search)
    if search is not None:
        stmt = stmt.where(search)
    if filters.unit_kind is not None:
        stmt = stmt.where(Unit.unit_kind == filters.unit_kind)
    if filters.is_global is not None:
        stmt = stmt.where(Unit.is_global == filters.is_global)
    if filters.is_active is not None:
        stmt = stmt.where(Unit.is_active == filters.is_active)
    return stmt


def _loggable(unit: Unit) -> dict[str, Any]:
    return {
        "code": unit.code,
        "name_en": unit.name_en,
        "name_my": unit.name_my,
        "unit_kind": unit.unit_kind.value,
        "is_global": unit.is_global,
        "is_active": unit.is_active,
    }
