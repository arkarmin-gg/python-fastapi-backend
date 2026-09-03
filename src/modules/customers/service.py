import uuid
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.foundation_enums import PartyStatus
from src.modules.audit_logs.service import record_audit_log
from src.modules.codes.service import generate_code
from src.modules.customers.exceptions import (
    CustomerCodeConflict,
    CustomerNotFound,
    InvalidCustomerPriceLevel,
)
from src.modules.customers.models import Customer
from src.modules.customers.schemas import CustomerCreate, CustomerFilters, CustomerUpdate
from src.modules.price_levels.models import PriceLevel
from src.pagination import Page, PaginationParams, paginate
from src.query_filters import SortSpec, apply_sort, search_clause

CUSTOMER_SORT_COLUMNS = {
    "code": Customer.code,
    "name": Customer.name,
    "customer_type": Customer.customer_type,
    "status": Customer.status,
    "created_at": Customer.created_at,
    "id": Customer.id,
}


async def get_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    customer_id: uuid.UUID,
) -> Customer | None:
    return await db.scalar(
        select(Customer).where(Customer.tenant_id == tenant_id, Customer.id == customer_id)
    )


async def list_customers(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: CustomerFilters,
    sort: tuple[SortSpec, ...],
) -> Page[Customer]:
    stmt = _apply_filters(select(Customer).where(Customer.tenant_id == tenant_id), filters)
    stmt = apply_sort(stmt, sort, CUSTOMER_SORT_COLUMNS)
    count_stmt = _apply_filters(
        select(func.count(Customer.id)).where(Customer.tenant_id == tenant_id),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def create(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: CustomerCreate,
    *,
    actor_user_id: uuid.UUID,
) -> Customer:
    if data.price_level_id is not None:
        await _ensure_active_price_level(db, tenant_id, data.price_level_id)
    customer = Customer(
        tenant_id=tenant_id,
        code=await generate_code(db, tenant_id, "customer"),
        **data.model_dump(),
    )
    db.add(customer)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="customers.create",
        entity_type="customer",
        entity_id=customer.id,
        after_json=_loggable(customer),
    )
    await db.commit()
    await db.refresh(customer)
    return customer


async def update(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    customer_id: uuid.UUID,
    data: CustomerUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> Customer:
    customer = await get_by_id(db, tenant_id, customer_id)
    if customer is None:
        raise CustomerNotFound()
    before = _loggable(customer)
    fields = data.model_dump(exclude_unset=True)
    if "price_level_id" in fields and fields["price_level_id"] is not None:
        await _ensure_active_price_level(db, tenant_id, fields["price_level_id"])
    for key, value in fields.items():
        setattr(customer, key, value)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="customers.update",
        entity_type="customer",
        entity_id=customer.id,
        before_json=before,
        after_json=_loggable(customer),
    )
    await db.commit()
    await db.refresh(customer)
    return customer


async def deactivate(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    customer_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    customer = await get_by_id(db, tenant_id, customer_id)
    if customer is None:
        raise CustomerNotFound()
    before = _loggable(customer)
    customer.status = PartyStatus.INACTIVE
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="customers.deactivate",
        entity_type="customer",
        entity_id=customer.id,
        before_json=before,
        after_json=_loggable(customer),
    )
    await db.commit()


async def _ensure_code_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    code: str,
    *,
    customer_id: uuid.UUID | None = None,
) -> None:
    existing = await db.scalar(
        select(Customer).where(Customer.tenant_id == tenant_id, Customer.code == code)
    )
    if existing is not None and existing.id != customer_id:
        raise CustomerCodeConflict()


async def _ensure_active_price_level(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    price_level_id: uuid.UUID,
) -> PriceLevel:
    price_level = await db.scalar(
        select(PriceLevel).where(
            PriceLevel.tenant_id == tenant_id,
            PriceLevel.id == price_level_id,
            PriceLevel.is_active.is_(True),
        )
    )
    if price_level is None:
        raise InvalidCustomerPriceLevel()
    return price_level


def _apply_filters[StmtT: Select[Any]](stmt: StmtT, filters: CustomerFilters) -> StmtT:
    search = search_clause(
        [Customer.code, Customer.name, Customer.phone, Customer.address],
        filters.search,
    )
    if search is not None:
        stmt = stmt.where(search)
    if filters.customer_type is not None:
        stmt = stmt.where(Customer.customer_type == filters.customer_type)
    if filters.price_level_id is not None:
        stmt = stmt.where(Customer.price_level_id == filters.price_level_id)
    if filters.status is not None:
        stmt = stmt.where(Customer.status == filters.status)
    return stmt


def _loggable(customer: Customer) -> dict[str, Any]:
    return {
        "code": customer.code,
        "name": customer.name,
        "customer_type": customer.customer_type.value,
        "price_level_id": str(customer.price_level_id)
        if customer.price_level_id is not None
        else None,
        "phone": customer.phone,
        "address": customer.address,
        "credit_limit": str(customer.credit_limit) if customer.credit_limit is not None else None,
        "status": customer.status.value,
    }
