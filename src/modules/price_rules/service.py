import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.foundation_enums import PartyStatus
from src.modules.audit_logs.service import record_audit_log
from src.modules.catalog.models import ProductVariant, VariantUnit
from src.modules.customers.models import Customer
from src.modules.price_levels.models import PriceLevel
from src.modules.price_rules.exceptions import (
    InvalidPriceRuleCustomer,
    InvalidPriceRuleEffectivePeriod,
    InvalidPriceRulePriceLevel,
    InvalidPriceRuleVariant,
    InvalidPriceRuleVariantUnit,
    PriceRuleNotFound,
    PriceRuleOverlapConflict,
)
from src.modules.price_rules.models import PriceRule
from src.modules.price_rules.schemas import PriceRuleCreate, PriceRuleFilters, PriceRuleUpdate
from src.pagination import Page, PaginationParams, paginate
from src.query_filters import SortSpec, apply_sort, where_gte_if_not_none, where_lte_if_not_none

PRICE_RULE_SORT_COLUMNS = {
    "effective_from": PriceRule.effective_from,
    "unit_price": PriceRule.unit_price,
    "product_variant_id": PriceRule.product_variant_id,
    "id": PriceRule.id,
}
INFINITY_END = datetime.max.replace(tzinfo=None)


async def get_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    price_rule_id: uuid.UUID,
) -> PriceRule | None:
    return await db.scalar(
        select(PriceRule).where(
            PriceRule.tenant_id == tenant_id,
            PriceRule.id == price_rule_id,
        )
    )


async def list_price_rules(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: PriceRuleFilters,
    sort: tuple[SortSpec, ...],
) -> Page[PriceRule]:
    stmt = _apply_filters(select(PriceRule).where(PriceRule.tenant_id == tenant_id), filters)
    stmt = apply_sort(stmt, sort, PRICE_RULE_SORT_COLUMNS)
    count_stmt = _apply_filters(
        select(func.count(PriceRule.id)).where(PriceRule.tenant_id == tenant_id),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def create(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: PriceRuleCreate,
    *,
    actor_user_id: uuid.UUID,
) -> PriceRule:
    await _ensure_valid_references(
        db,
        tenant_id,
        data.product_variant_id,
        data.variant_unit_id,
        data.price_level_id,
        data.customer_id,
    )
    await _ensure_no_overlap(
        db,
        tenant_id,
        product_variant_id=data.product_variant_id,
        variant_unit_id=data.variant_unit_id,
        price_level_id=data.price_level_id,
        customer_id=data.customer_id,
        min_quantity=data.min_quantity,
        effective_from=data.effective_from,
        effective_to=data.effective_to,
        is_active=data.is_active,
    )
    price_rule = PriceRule(tenant_id=tenant_id, **data.model_dump())
    db.add(price_rule)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="price_rules.create",
        entity_type="price_rule",
        entity_id=price_rule.id,
        after_json=_loggable(price_rule),
    )
    await db.commit()
    await db.refresh(price_rule)
    return price_rule


async def update(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    price_rule_id: uuid.UUID,
    data: PriceRuleUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> PriceRule:
    price_rule = await get_by_id(db, tenant_id, price_rule_id)
    if price_rule is None:
        raise PriceRuleNotFound()
    before = _loggable(price_rule)
    fields = data.model_dump(exclude_unset=True)

    product_variant_id = fields.get("product_variant_id", price_rule.product_variant_id)
    variant_unit_id = fields.get("variant_unit_id", price_rule.variant_unit_id)
    price_level_id = fields.get("price_level_id", price_rule.price_level_id)
    customer_id = fields.get("customer_id", price_rule.customer_id)
    min_quantity = fields.get("min_quantity", price_rule.min_quantity)
    effective_from = fields.get("effective_from", price_rule.effective_from)
    effective_to = fields.get("effective_to", price_rule.effective_to)
    is_active = fields.get("is_active", price_rule.is_active)

    _ensure_valid_effective_period(effective_from, effective_to)
    await _ensure_valid_references(
        db,
        tenant_id,
        product_variant_id,
        variant_unit_id,
        price_level_id,
        customer_id,
    )
    await _ensure_no_overlap(
        db,
        tenant_id,
        product_variant_id=product_variant_id,
        variant_unit_id=variant_unit_id,
        price_level_id=price_level_id,
        customer_id=customer_id,
        min_quantity=min_quantity,
        effective_from=effective_from,
        effective_to=effective_to,
        is_active=is_active,
        price_rule_id=price_rule.id,
    )

    for key, value in fields.items():
        setattr(price_rule, key, value)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="price_rules.update",
        entity_type="price_rule",
        entity_id=price_rule.id,
        before_json=before,
        after_json=_loggable(price_rule),
    )
    await db.commit()
    await db.refresh(price_rule)
    return price_rule


async def deactivate(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    price_rule_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    price_rule = await get_by_id(db, tenant_id, price_rule_id)
    if price_rule is None:
        raise PriceRuleNotFound()
    before = _loggable(price_rule)
    price_rule.is_active = False
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="price_rules.deactivate",
        entity_type="price_rule",
        entity_id=price_rule.id,
        before_json=before,
        after_json=_loggable(price_rule),
    )
    await db.commit()


async def resolve_unit_price(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    product_variant_id: uuid.UUID,
    variant_unit_id: uuid.UUID,
    price_level_id: uuid.UUID,
    customer_id: uuid.UUID | None,
    quantity: Decimal,
    effective_at: datetime,
) -> tuple[Decimal | None, uuid.UUID | None]:
    price_rule = await resolve_price_rule(
        db,
        tenant_id,
        product_variant_id=product_variant_id,
        variant_unit_id=variant_unit_id,
        price_level_id=price_level_id,
        customer_id=customer_id,
        quantity=quantity,
        effective_at=effective_at,
    )
    if price_rule is not None:
        return price_rule.unit_price, price_rule.id

    variant = await db.scalar(
        select(ProductVariant).where(
            ProductVariant.tenant_id == tenant_id,
            ProductVariant.id == product_variant_id,
            ProductVariant.is_active.is_(True),
        )
    )
    if variant is None:
        raise InvalidPriceRuleVariant()
    return variant.default_sale_price, None


async def resolve_price_rule(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    product_variant_id: uuid.UUID,
    variant_unit_id: uuid.UUID,
    price_level_id: uuid.UUID,
    customer_id: uuid.UUID | None,
    quantity: Decimal,
    effective_at: datetime,
) -> PriceRule | None:
    customer_specific_rank = case((PriceRule.customer_id.is_not(None), 0), else_=1)
    min_quantity_rank = case((PriceRule.min_quantity.is_not(None), 0), else_=1)
    stmt = (
        select(PriceRule)
        .where(
            PriceRule.tenant_id == tenant_id,
            PriceRule.product_variant_id == product_variant_id,
            PriceRule.variant_unit_id == variant_unit_id,
            PriceRule.price_level_id == price_level_id,
            PriceRule.is_active.is_(True),
            PriceRule.effective_from <= effective_at,
            or_(PriceRule.effective_to.is_(None), PriceRule.effective_to > effective_at),
            or_(PriceRule.min_quantity.is_(None), PriceRule.min_quantity <= quantity),
        )
        .order_by(
            customer_specific_rank.asc(),
            min_quantity_rank.asc(),
            PriceRule.min_quantity.desc().nullslast(),
            PriceRule.effective_from.desc(),
            PriceRule.id.asc(),
        )
    )
    if customer_id is None:
        stmt = stmt.where(PriceRule.customer_id.is_(None))
    else:
        stmt = stmt.where(
            or_(PriceRule.customer_id == customer_id, PriceRule.customer_id.is_(None))
        )
    return await db.scalar(stmt)


async def _ensure_valid_references(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    variant_unit_id: uuid.UUID,
    price_level_id: uuid.UUID,
    customer_id: uuid.UUID | None,
) -> None:
    await _ensure_active_product_variant(db, tenant_id, product_variant_id)
    await _ensure_active_variant_unit(db, tenant_id, product_variant_id, variant_unit_id)
    await _ensure_active_price_level(db, tenant_id, price_level_id)
    if customer_id is not None:
        await _ensure_active_customer(db, tenant_id, customer_id)


async def _ensure_active_product_variant(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
) -> ProductVariant:
    product_variant = await db.scalar(
        select(ProductVariant).where(
            ProductVariant.tenant_id == tenant_id,
            ProductVariant.id == product_variant_id,
            ProductVariant.is_active.is_(True),
        )
    )
    if product_variant is None:
        raise InvalidPriceRuleVariant()
    return product_variant


async def _ensure_active_variant_unit(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    variant_unit_id: uuid.UUID,
) -> VariantUnit:
    variant_unit = await db.scalar(
        select(VariantUnit).where(
            VariantUnit.tenant_id == tenant_id,
            VariantUnit.id == variant_unit_id,
            VariantUnit.product_variant_id == product_variant_id,
            VariantUnit.is_active.is_(True),
        )
    )
    if variant_unit is None:
        raise InvalidPriceRuleVariantUnit()
    return variant_unit


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
        raise InvalidPriceRulePriceLevel()
    return price_level


async def _ensure_active_customer(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    customer_id: uuid.UUID,
) -> Customer:
    customer = await db.scalar(
        select(Customer).where(
            Customer.tenant_id == tenant_id,
            Customer.id == customer_id,
            Customer.status == PartyStatus.ACTIVE,
        )
    )
    if customer is None:
        raise InvalidPriceRuleCustomer()
    return customer


async def _ensure_no_overlap(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    product_variant_id: uuid.UUID,
    variant_unit_id: uuid.UUID,
    price_level_id: uuid.UUID,
    customer_id: uuid.UUID | None,
    min_quantity: Decimal | None,
    effective_from: datetime,
    effective_to: datetime | None,
    is_active: bool,
    price_rule_id: uuid.UUID | None = None,
) -> None:
    if not is_active:
        return

    stmt = select(PriceRule).where(
        PriceRule.tenant_id == tenant_id,
        PriceRule.product_variant_id == product_variant_id,
        PriceRule.variant_unit_id == variant_unit_id,
        PriceRule.price_level_id == price_level_id,
        PriceRule.is_active.is_(True),
        PriceRule.effective_from < (effective_to or INFINITY_END),
        or_(PriceRule.effective_to.is_(None), PriceRule.effective_to > effective_from),
    )
    stmt = _where_nullable_scope(stmt, PriceRule.customer_id, customer_id)
    stmt = _where_nullable_scope(stmt, PriceRule.min_quantity, min_quantity)
    if price_rule_id is not None:
        stmt = stmt.where(PriceRule.id != price_rule_id)

    existing = await db.scalar(stmt)
    if existing is not None:
        raise PriceRuleOverlapConflict()


def _ensure_valid_effective_period(
    effective_from: datetime,
    effective_to: datetime | None,
) -> None:
    if effective_to is not None and effective_to <= effective_from:
        raise InvalidPriceRuleEffectivePeriod()


def _where_nullable_scope[StmtT: Select[Any]](
    stmt: StmtT,
    column: Any,
    value: object | None,
) -> StmtT:
    if value is None:
        return stmt.where(column.is_(None))
    return stmt.where(column == value)


def _apply_filters[StmtT: Select[Any]](stmt: StmtT, filters: PriceRuleFilters) -> StmtT:
    if filters.product_variant_id is not None:
        stmt = stmt.where(PriceRule.product_variant_id == filters.product_variant_id)
    if filters.variant_unit_id is not None:
        stmt = stmt.where(PriceRule.variant_unit_id == filters.variant_unit_id)
    if filters.price_level_id is not None:
        stmt = stmt.where(PriceRule.price_level_id == filters.price_level_id)
    if filters.customer_id is not None:
        stmt = stmt.where(PriceRule.customer_id == filters.customer_id)
    if filters.currency_code is not None:
        stmt = stmt.where(PriceRule.currency_code == filters.currency_code)
    if filters.is_active is not None:
        stmt = stmt.where(PriceRule.is_active == filters.is_active)
    stmt = where_gte_if_not_none(stmt, PriceRule.effective_from, filters.effective_from_gte)
    stmt = where_lte_if_not_none(stmt, PriceRule.effective_from, filters.effective_from_lte)
    return stmt


def _loggable(price_rule: PriceRule) -> dict[str, Any]:
    return {
        "product_variant_id": str(price_rule.product_variant_id),
        "variant_unit_id": str(price_rule.variant_unit_id),
        "price_level_id": str(price_rule.price_level_id),
        "customer_id": str(price_rule.customer_id) if price_rule.customer_id is not None else None,
        "min_quantity": str(price_rule.min_quantity)
        if price_rule.min_quantity is not None
        else None,
        "currency_code": price_rule.currency_code,
        "unit_price": str(price_rule.unit_price),
        "effective_from": price_rule.effective_from.isoformat(),
        "effective_to": price_rule.effective_to.isoformat()
        if price_rule.effective_to is not None
        else None,
        "is_active": price_rule.is_active,
    }
