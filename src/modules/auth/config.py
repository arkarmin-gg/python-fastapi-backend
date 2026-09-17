from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AUTH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    JWT_SECRET: str = Field(min_length=32)
    JWT_ALG: str = "HS256"
    JWT_ACCESS_EXP_MINUTES: int = 30
    REFRESH_TOKEN_EXP_DAYS: int = 14


@lru_cache
def get_auth_settings() -> AuthSettings:
    return AuthSettings()


auth_settings = get_auth_settings()
