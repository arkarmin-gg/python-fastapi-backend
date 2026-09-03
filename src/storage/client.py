from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import aioboto3
from botocore.config import Config

from src.storage.config import storage_settings
from src.storage.exceptions import StorageNotConfigured

_session = aioboto3.Session()


@asynccontextmanager
async def get_s3_client() -> AsyncIterator:
    if not storage_settings.is_configured:
        raise StorageNotConfigured()
    async with _session.client(
        "s3",
        region_name=storage_settings.REGION,
        endpoint_url=storage_settings.ENDPOINT_URL,
        aws_access_key_id=storage_settings.ACCESS_KEY_ID,
        aws_secret_access_key=storage_settings.SECRET_ACCESS_KEY,
        use_ssl=storage_settings.USE_SSL,
        config=Config(s3={"addressing_style": "path"}),
    ) as client:
        yield client
