import uuid
from datetime import datetime
from typing import Annotated

from fastapi import Query
from pydantic import Field, model_validator

from src.foundation_enums import LocationType
from src.pagination import Page
from src.query_filters import build_query_model, normalize_search
from src.schemas import RequestSchema, ResponseSchema


class LocationRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    parent_location_id: uuid.UUID | None
    code: str
    name: str
    location_type: LocationType
    is_sellable: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


LocationListResponse = Page[LocationRead]


class LocationFilters(RequestSchema):
    search: str | None = None
    parent_location_id: uuid.UUID | None = None
    location_type: LocationType | None = None
    is_sellable: bool | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def normalize(self):
        self.search = normalize_search(self.search)
        return self


def location_filters(
    search: Annotated[str | None, Query()] = None,
    parent_location_id: Annotated[uuid.UUID | None, Query()] = None,
    location_type: Annotated[LocationType | None, Query()] = None,
    is_sellable: Annotated[bool | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = None,
) -> LocationFilters:
    return build_query_model(
        LocationFilters,
        search=search,
        parent_location_id=parent_location_id,
        location_type=location_type,
        is_sellable=is_sellable,
        is_active=is_active,
    )


class LocationCreate(RequestSchema):
    parent_location_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=180)
    location_type: LocationType
    is_sellable: bool = False
    is_active: bool = True


class LocationUpdate(RequestSchema):
    parent_location_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=180)
    location_type: LocationType | None = None
    is_sellable: bool | None = None
    is_active: bool | None = None
