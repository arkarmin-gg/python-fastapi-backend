from enum import StrEnum
from functools import lru_cache
from typing import Annotated

from pydantic import PostgresDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    PROJECT_NAME: str = "python-fastapi-backend"
    ENVIRONMENT: Environment = Environment.LOCAL
    API_V1_PREFIX: str = "/api/v1"

    DATABASE_URL: PostgresDsn
    DB_ECHO: bool = False

    # Accepts a comma-separated string ("http://a,http://b") or a JSON list.
    CORS_ORIGINS: Annotated[list[str], NoDecode] = ["*"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_cors(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def reject_production_wildcard_cors(self):
        if self.ENVIRONMENT == Environment.PRODUCTION and "*" in self.CORS_ORIGINS:
            raise ValueError("CORS_ORIGINS cannot contain '*' in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
