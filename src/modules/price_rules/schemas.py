import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import Query
from pydantic import Field, model_validator

from src.pagination import Page
from src.query_filters import build_query_model, parse_datetime_range, require_timezone_aware
from src.schemas import RequestSchema, ResponseSchema


class PriceRuleRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    product_variant_id: uuid.UUID
    variant_unit_id: uuid.UUID
    price_level_id: uuid.UUID
    customer_id: uuid.UUID | None
    min_quantity: Decimal | None
    currency_code: str
    unit_price: Decimal
    effective_from: datetime
    effective_to: datetime | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


PriceRuleListResponse = Page[PriceRuleRead]


class PriceRuleFilters(RequestSchema):
    product_variant_id: uuid.UUID | None = None
    variant_unit_id: uuid.UUID | None = None
    price_level_id: uuid.UUID | None = None
    customer_id: uuid.UUID | None = None
    currency_code: str | None = Field(default=None, min_length=3, max_length=3)
    is_active: bool | None = None
    effective_from_gte: datetime | str | None = None
    effective_from_lte: datetime | str | None = None

    @model_validator(mode="after")
    def normalize(self):
        self.effective_from_gte, self.effective_from_lte = parse_datetime_range(
            self.effective_from_gte,
            self.effective_from_lte,
            from_field="effective_from_gte",
            to_field="effective_from_lte",
        )
        if self.currency_code is not None:
            self.currency_code = self.currency_code.upper()
        return self


def price_rule_filters(
    product_variant_id: Annotated[uuid.UUID | None, Query()] = None,
    variant_unit_id: Annotated[uuid.UUID | None, Query()] = None,
    price_level_id: Annotated[uuid.UUID | None, Query()] = None,
    customer_id: Annotated[uuid.UUID | None, Query()] = None,
    currency_code: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
    is_active: Annotated[bool | None, Query()] = None,
    effective_from_gte: Annotated[str | None, Query()] = None,
    effective_from_lte: Annotated[str | None, Query()] = None,
) -> PriceRuleFilters:
    return build_query_model(
        PriceRuleFilters,
        product_variant_id=product_variant_id,
        variant_unit_id=variant_unit_id,
        price_level_id=price_level_id,
        customer_id=customer_id,
        currency_code=currency_code,
        is_active=is_active,
        effective_from_gte=effective_from_gte,
        effective_from_lte=effective_from_lte,
    )


class PriceRuleCreate(RequestSchema):
    product_variant_id: uuid.UUID
    variant_unit_id: uuid.UUID
    price_level_id: uuid.UUID
    customer_id: uuid.UUID | None = None
    min_quantity: Decimal | None = Field(default=None, gt=0)
    currency_code: str = Field(default="MMK", min_length=3, max_length=3)
    unit_price: Decimal = Field(gt=0, max_digits=20, decimal_places=4)
    effective_from: datetime
    effective_to: datetime | None = None
    is_active: bool = True

    @model_validator(mode="after")
    def validate_dates(self):
        _validate_effective_period(self.effective_from, self.effective_to)
        self.currency_code = self.currency_code.upper()
        return self


class PriceRuleUpdate(RequestSchema):
    product_variant_id: uuid.UUID | None = None
    variant_unit_id: uuid.UUID | None = None
    price_level_id: uuid.UUID | None = None
    customer_id: uuid.UUID | None = None
    min_quantity: Decimal | None = Field(default=None, gt=0)
    currency_code: str | None = Field(default=None, min_length=3, max_length=3)
    unit_price: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=4)
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def normalize(self):
        if self.effective_from is not None:
            require_timezone_aware(self.effective_from, "effective_from")
        if self.effective_to is not None:
            require_timezone_aware(self.effective_to, "effective_to")
        if self.currency_code is not None:
            self.currency_code = self.currency_code.upper()
        return self


def _validate_effective_period(effective_from: datetime, effective_to: datetime | None) -> None:
    require_timezone_aware(effective_from, "effective_from")
    require_timezone_aware(effective_to, "effective_to")
    if effective_to is not None and effective_to <= effective_from:
        raise ValueError("effective_to must be later than effective_from")
