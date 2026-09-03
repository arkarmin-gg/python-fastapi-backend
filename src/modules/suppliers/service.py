import uuid
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.foundation_enums import PartyStatus
from src.modules.audit_logs.service import record_audit_log
from src.modules.codes.service import generate_code
from src.modules.suppliers.exceptions import SupplierCodeConflict, SupplierNotFound
from src.modules.suppliers.models import Supplier
from src.modules.suppliers.schemas import SupplierCreate, SupplierFilters, SupplierUpdate
from src.pagination import Page, PaginationParams, paginate
from src.query_filters import SortSpec, apply_sort, search_clause

SUPPLIER_SORT_COLUMNS = {
    "code": Supplier.code,
    "name": Supplier.name,
    "supplier_type": Supplier.supplier_type,
    "status": Supplier.status,
    "created_at": Supplier.created_at,
    "id": Supplier.id,
}


async def get_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
) -> Supplier | None:
    return await db.scalar(
        select(Supplier).where(Supplier.tenant_id == tenant_id, Supplier.id == supplier_id)
    )


async def list_suppliers(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: SupplierFilters,
    sort: tuple[SortSpec, ...],
) -> Page[Supplier]:
    stmt = _apply_filters(select(Supplier).where(Supplier.tenant_id == tenant_id), filters)
    stmt = apply_sort(stmt, sort, SUPPLIER_SORT_COLUMNS)
    count_stmt = _apply_filters(
        select(func.count(Supplier.id)).where(Supplier.tenant_id == tenant_id),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def create(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: SupplierCreate,
    *,
    actor_user_id: uuid.UUID,
) -> Supplier:
    supplier = Supplier(
        tenant_id=tenant_id,
        code=await generate_code(db, tenant_id, "supplier"),
        **data.model_dump(),
    )
    db.add(supplier)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="suppliers.create",
        entity_type="supplier",
        entity_id=supplier.id,
        after_json=_loggable(supplier),
    )
    await db.commit()
    await db.refresh(supplier)
    return supplier


async def update(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
    data: SupplierUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> Supplier:
    supplier = await get_by_id(db, tenant_id, supplier_id)
    if supplier is None:
        raise SupplierNotFound()
    before = _loggable(supplier)
    fields = data.model_dump(exclude_unset=True)
    for key, value in fields.items():
        setattr(supplier, key, value)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="suppliers.update",
        entity_type="supplier",
        entity_id=supplier.id,
        before_json=before,
        after_json=_loggable(supplier),
    )
    await db.commit()
    await db.refresh(supplier)
    return supplier


async def deactivate(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    supplier = await get_by_id(db, tenant_id, supplier_id)
    if supplier is None:
        raise SupplierNotFound()
    before = _loggable(supplier)
    supplier.status = PartyStatus.INACTIVE
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="suppliers.deactivate",
        entity_type="supplier",
        entity_id=supplier.id,
        before_json=before,
        after_json=_loggable(supplier),
    )
    await db.commit()


async def _ensure_code_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    code: str,
    *,
    supplier_id: uuid.UUID | None = None,
) -> None:
    existing = await db.scalar(
        select(Supplier).where(Supplier.tenant_id == tenant_id, Supplier.code == code)
    )
    if existing is not None and existing.id != supplier_id:
        raise SupplierCodeConflict()


def _apply_filters[StmtT: Select[Any]](stmt: StmtT, filters: SupplierFilters) -> StmtT:
    search = search_clause(
        [Supplier.code, Supplier.name, Supplier.phone, Supplier.address],
        filters.search,
    )
    if search is not None:
        stmt = stmt.where(search)
    if filters.supplier_type is not None:
        stmt = stmt.where(Supplier.supplier_type == filters.supplier_type)
    if filters.status is not None:
        stmt = stmt.where(Supplier.status == filters.status)
    return stmt


def _loggable(supplier: Supplier) -> dict[str, Any]:
    return {
        "code": supplier.code,
        "name": supplier.name,
        "supplier_type": supplier.supplier_type.value,
        "phone": supplier.phone,
        "address": supplier.address,
        "status": supplier.status.value,
    }
