from pydantic_settings import BaseSettings, SettingsConfigDict


class StorageConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="S3_", env_file=".env", extra="ignore")

    BUCKET: str = ""
    ACCESS_KEY_ID: str = ""
    SECRET_ACCESS_KEY: str = ""
    REGION: str = "us-east-1"
    ENDPOINT_URL: str | None = None
    USE_SSL: bool = True
    PRESIGN_EXPIRY_SECONDS: int = 3600

    @property
    def is_configured(self) -> bool:
        return bool(self.BUCKET and self.ACCESS_KEY_ID and self.SECRET_ACCESS_KEY)


storage_settings = StorageConfig()
