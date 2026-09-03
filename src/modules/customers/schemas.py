import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import Query
from pydantic import Field, model_validator

from src.foundation_enums import CustomerType, PartyStatus
from src.pagination import Page
from src.query_filters import build_query_model, normalize_search
from src.schemas import RequestSchema, ResponseSchema


class CustomerRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    code: str
    name: str
    customer_type: CustomerType
    price_level_id: uuid.UUID | None
    phone: str | None
    address: str | None
    credit_limit: Decimal | None
    status: PartyStatus
    created_at: datetime
    updated_at: datetime


CustomerListResponse = Page[CustomerRead]


class CustomerFilters(RequestSchema):
    search: str | None = None
    customer_type: CustomerType | None = None
    price_level_id: uuid.UUID | None = None
    status: PartyStatus | None = None

    @model_validator(mode="after")
    def normalize(self):
        self.search = normalize_search(self.search)
        return self


def customer_filters(
    search: Annotated[str | None, Query()] = None,
    customer_type: Annotated[CustomerType | None, Query()] = None,
    price_level_id: Annotated[uuid.UUID | None, Query()] = None,
    status: Annotated[PartyStatus | None, Query()] = None,
) -> CustomerFilters:
    return build_query_model(
        CustomerFilters,
        search=search,
        customer_type=customer_type,
        price_level_id=price_level_id,
        status=status,
    )


class CustomerCreate(RequestSchema):
    name: str = Field(min_length=1, max_length=240)
    customer_type: CustomerType = CustomerType.RETAIL
    price_level_id: uuid.UUID | None = None
    phone: str | None = Field(default=None, max_length=50)
    address: str | None = None
    credit_limit: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=4)
    status: PartyStatus = PartyStatus.ACTIVE


class CustomerUpdate(RequestSchema):
    name: str | None = Field(default=None, min_length=1, max_length=240)
    customer_type: CustomerType | None = None
    price_level_id: uuid.UUID | None = None
    phone: str | None = Field(default=None, max_length=50)
    address: str | None = None
    credit_limit: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=4)
    status: PartyStatus | None = None
