import uuid
from datetime import datetime
from typing import Annotated

from fastapi import Query
from pydantic import Field, model_validator

from src.foundation_enums import TenantStatus
from src.pagination import Page
from src.query_filters import build_query_model, normalize_search
from src.schemas import RequestSchema, ResponseSchema


class TenantRead(ResponseSchema):
    id: uuid.UUID
    code: str
    name: str
    legal_name: str | None
    currency_code: str
    timezone: str
    locale: str
    status: TenantStatus
    created_at: datetime
    updated_at: datetime


TenantListResponse = Page[TenantRead]


class TenantFilters(RequestSchema):
    search: str | None = None
    status: TenantStatus | None = None

    @model_validator(mode="after")
    def normalize(self):
        self.search = normalize_search(self.search)
        return self


def tenant_filters(
    search: Annotated[str | None, Query()] = None,
    status: Annotated[TenantStatus | None, Query()] = None,
) -> TenantFilters:
    return build_query_model(TenantFilters, search=search, status=status)


class TenantCreate(RequestSchema):
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    legal_name: str | None = Field(default=None, max_length=250)
    currency_code: str = Field(default="MMK", min_length=3, max_length=3)
    timezone: str = Field(default="Asia/Yangon", min_length=1, max_length=80)
    locale: str = Field(default="my-MM", min_length=1, max_length=20)
    status: TenantStatus = TenantStatus.ACTIVE


class TenantUpdate(RequestSchema):
    code: str | None = Field(default=None, min_length=1, max_length=80)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    legal_name: str | None = Field(default=None, max_length=250)
    currency_code: str | None = Field(default=None, min_length=3, max_length=3)
    timezone: str | None = Field(default=None, min_length=1, max_length=80)
    locale: str | None = Field(default=None, min_length=1, max_length=20)
    status: TenantStatus | None = None
