from pydantic import Field, model_validator

from src.schemas import RequestSchema


class LoginRequest(RequestSchema):
    organization_id: str | None = Field(
        default=None, description="Organization UUID. Required if organization_code is omitted."
    )
    organization_code: str | None = Field(default=None, min_length=1, max_length=80)
    identifier: str = Field(min_length=1, max_length=255, description="User email or phone.")
    password: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def organization_identifier_required(self):
        if self.organization_id is None and self.organization_code is None:
            raise ValueError("organization_id or organization_code is required")
        return self


class TokenResponse(RequestSchema):
    access_token: str = Field(description="Short-lived JWT used to authenticate user requests.")
    refresh_token: str = Field(
        description="Long-lived opaque token used to obtain a new access token."
    )
    token_type: str = Field(default="bearer")


class RefreshRequest(RequestSchema):
    refresh_token: str


class ChangePasswordRequest(RequestSchema):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)
