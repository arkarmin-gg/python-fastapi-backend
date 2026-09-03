import uuid
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.audit_logs.service import record_audit_log
from src.modules.codes.service import generate_code
from src.modules.locations.exceptions import (
    InvalidParentLocation,
    LocationCodeConflict,
    LocationNotFound,
)
from src.modules.locations.models import Location
from src.modules.locations.schemas import LocationCreate, LocationFilters, LocationUpdate
from src.pagination import Page, PaginationParams, paginate
from src.query_filters import SortSpec, apply_sort, search_clause

LOCATION_SORT_COLUMNS = {
    "code": Location.code,
    "name": Location.name,
    "location_type": Location.location_type,
    "created_at": Location.created_at,
    "id": Location.id,
}


async def get_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    location_id: uuid.UUID,
) -> Location | None:
    return await db.scalar(
        select(Location).where(Location.tenant_id == tenant_id, Location.id == location_id)
    )


async def list_locations(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: LocationFilters,
    sort: tuple[SortSpec, ...],
) -> Page[Location]:
    stmt = _apply_filters(select(Location).where(Location.tenant_id == tenant_id), filters)
    stmt = apply_sort(stmt, sort, LOCATION_SORT_COLUMNS)
    count_stmt = _apply_filters(
        select(func.count(Location.id)).where(Location.tenant_id == tenant_id),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def create(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: LocationCreate,
    *,
    actor_user_id: uuid.UUID,
) -> Location:
    if data.parent_location_id is not None:
        await _ensure_active_parent_exists(db, tenant_id, data.parent_location_id)
    location = Location(
        tenant_id=tenant_id,
        code=await generate_code(db, tenant_id, "location"),
        **data.model_dump(),
    )
    db.add(location)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="locations.create",
        entity_type="location",
        entity_id=location.id,
        after_json=_loggable(location),
    )
    await db.commit()
    await db.refresh(location)
    return location


async def update(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    location_id: uuid.UUID,
    data: LocationUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> Location:
    location = await get_by_id(db, tenant_id, location_id)
    if location is None:
        raise LocationNotFound()
    before = _loggable(location)
    fields = data.model_dump(exclude_unset=True)
    if "parent_location_id" in fields:
        await _ensure_valid_parent(db, tenant_id, location.id, fields["parent_location_id"])
    for key, value in fields.items():
        setattr(location, key, value)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="locations.update",
        entity_type="location",
        entity_id=location.id,
        before_json=before,
        after_json=_loggable(location),
    )
    await db.commit()
    await db.refresh(location)
    return location


async def deactivate(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    location_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    location = await get_by_id(db, tenant_id, location_id)
    if location is None:
        raise LocationNotFound()
    before = _loggable(location)
    location.is_active = False
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="locations.deactivate",
        entity_type="location",
        entity_id=location.id,
        before_json=before,
        after_json=_loggable(location),
    )
    await db.commit()


async def _ensure_code_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    code: str,
    *,
    location_id: uuid.UUID | None = None,
) -> None:
    existing = await db.scalar(
        select(Location).where(Location.tenant_id == tenant_id, Location.code == code)
    )
    if existing is not None and existing.id != location_id:
        raise LocationCodeConflict()


async def _ensure_active_parent_exists(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    parent_location_id: uuid.UUID,
) -> Location:
    parent = await get_by_id(db, tenant_id, parent_location_id)
    if parent is None or not parent.is_active:
        raise InvalidParentLocation()
    return parent


async def _ensure_valid_parent(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    location_id: uuid.UUID,
    parent_location_id: uuid.UUID | None,
) -> None:
    if parent_location_id is None:
        return
    if parent_location_id == location_id:
        raise InvalidParentLocation()
    parent = await _ensure_active_parent_exists(db, tenant_id, parent_location_id)
    while parent.parent_location_id is not None:
        if parent.parent_location_id == location_id:
            raise InvalidParentLocation()
        parent = await _ensure_active_parent_exists(db, tenant_id, parent.parent_location_id)


def _apply_filters[StmtT: Select[Any]](stmt: StmtT, filters: LocationFilters) -> StmtT:
    search = search_clause([Location.code, Location.name], filters.search)
    if search is not None:
        stmt = stmt.where(search)
    if filters.parent_location_id is not None:
        stmt = stmt.where(Location.parent_location_id == filters.parent_location_id)
    if filters.location_type is not None:
        stmt = stmt.where(Location.location_type == filters.location_type)
    if filters.is_sellable is not None:
        stmt = stmt.where(Location.is_sellable == filters.is_sellable)
    if filters.is_active is not None:
        stmt = stmt.where(Location.is_active == filters.is_active)
    return stmt


def _loggable(location: Location) -> dict[str, Any]:
    return {
        "parent_location_id": str(location.parent_location_id)
        if location.parent_location_id is not None
        else None,
        "code": location.code,
        "name": location.name,
        "location_type": location.location_type.value,
        "is_sellable": location.is_sellable,
        "is_active": location.is_active,
    }
