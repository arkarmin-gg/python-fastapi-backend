import uuid
from datetime import datetime
from typing import Annotated

from fastapi import Query
from pydantic import Field, model_validator

from src.foundation_enums import UserStatus
from src.pagination import Page
from src.query_filters import build_query_model, normalize_search
from src.schemas import RequestSchema, ResponseSchema


class UserRead(ResponseSchema):
    id: uuid.UUID
    name: str
    email: str | None
    phone: str | None
    status: UserStatus
    last_login_at: datetime | None
    last_logout_at: datetime | None
    created_at: datetime
    updated_at: datetime
    permission_codes: list[str] = Field(default_factory=list)


UserListResponse = Page[UserRead]


class UserFilters(RequestSchema):
    search: str | None = None
    status: UserStatus | None = None

    @model_validator(mode="after")
    def normalize(self):
        self.search = normalize_search(self.search)
        return self


def user_filters(
    search: Annotated[str | None, Query()] = None,
    status: Annotated[UserStatus | None, Query()] = None,
) -> UserFilters:
    return build_query_model(UserFilters, search=search, status=status)


class UserCreate(RequestSchema):
    name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    password: str = Field(min_length=8, max_length=128)
    role_ids: list[uuid.UUID] = Field(default_factory=list)


class UserUpdate(RequestSchema):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    status: UserStatus | None = None
    role_ids: list[uuid.UUID] | None = None


class UserProfileUpdate(RequestSchema):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
