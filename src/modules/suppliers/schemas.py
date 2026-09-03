import uuid
from datetime import datetime
from typing import Annotated

from fastapi import Query
from pydantic import Field, model_validator

from src.foundation_enums import PartyStatus, SupplierType
from src.pagination import Page
from src.query_filters import build_query_model, normalize_search
from src.schemas import RequestSchema, ResponseSchema


class SupplierRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    code: str
    name: str
    supplier_type: SupplierType
    phone: str | None
    address: str | None
    status: PartyStatus
    created_at: datetime
    updated_at: datetime


SupplierListResponse = Page[SupplierRead]


class SupplierFilters(RequestSchema):
    search: str | None = None
    supplier_type: SupplierType | None = None
    status: PartyStatus | None = None

    @model_validator(mode="after")
    def normalize(self):
        self.search = normalize_search(self.search)
        return self


def supplier_filters(
    search: Annotated[str | None, Query()] = None,
    supplier_type: Annotated[SupplierType | None, Query()] = None,
    status: Annotated[PartyStatus | None, Query()] = None,
) -> SupplierFilters:
    return build_query_model(
        SupplierFilters,
        search=search,
        supplier_type=supplier_type,
        status=status,
    )


class SupplierCreate(RequestSchema):
    name: str = Field(min_length=1, max_length=240)
    supplier_type: SupplierType = SupplierType.LOCAL
    phone: str | None = Field(default=None, max_length=50)
    address: str | None = None
    status: PartyStatus = PartyStatus.ACTIVE


class SupplierUpdate(RequestSchema):
    name: str | None = Field(default=None, min_length=1, max_length=240)
    supplier_type: SupplierType | None = None
    phone: str | None = Field(default=None, max_length=50)
    address: str | None = None
    status: PartyStatus | None = None
