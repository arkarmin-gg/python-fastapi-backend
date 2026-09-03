from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    JWT_SECRET: str = "38c8c7ab9fdcac67bf3565901c43d6a3a397d7ed72ca39df2acf7dcc70b01c33"
    JWT_ALG: str = "HS256"
    JWT_ACCESS_EXP_MINUTES: int = 30
    REFRESH_TOKEN_EXP_DAYS: int = 14


@lru_cache
def get_auth_settings() -> AuthSettings:
    return AuthSettings()


auth_settings = get_auth_settings()
