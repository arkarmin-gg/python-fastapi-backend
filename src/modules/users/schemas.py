import uuid
from datetime import datetime
from typing import Annotated

from fastapi import Query
from pydantic import EmailStr, Field, model_validator

from src.foundation_enums import UserStatus
from src.pagination import Page
from src.query_filters import build_query_model, normalize_search
from src.schemas import RequestSchema, ResponseSchema


class UserRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    employee_id: uuid.UUID | None
    name: str
    email: EmailStr | None
    phone: str | None
    status: UserStatus
    role_ids: list[uuid.UUID]
    permission_codes: list[str]
    last_login_at: datetime | None
    last_logout_at: datetime | None
    created_at: datetime
    updated_at: datetime


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
    employee_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    password: str = Field(min_length=8, max_length=128)
    status: UserStatus = UserStatus.ACTIVE
    role_ids: list[uuid.UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_identifier(self):
        if self.email is None and self.phone is None:
            raise ValueError("email or phone is required")
        return self


class UserUpdate(RequestSchema):
    employee_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    status: UserStatus | None = None
    role_ids: list[uuid.UUID] | None = None


class UserProfileUpdate(RequestSchema):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
