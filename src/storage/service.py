import functools
import uuid
from contextlib import suppress

import botocore.session
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import UploadFile

from src.storage.client import get_s3_client
from src.storage.config import storage_settings
from src.storage.constants import (
    ALLOWED_IMAGE_CONTENT_TYPES,
    IMAGE_CONTENT_TYPE_EXTENSIONS,
    MAX_IMAGE_BYTES,
)
from src.storage.exceptions import FileTooLarge, StorageError, UnsupportedFileType
from src.storage.schemas import StoredObject


def _build_key(prefix: str, extension: str) -> str:
    """A collision-free object key: `<prefix>/<random-hex>.<ext>`."""
    return f"{prefix.strip('/')}/{uuid.uuid4().hex}.{extension.lstrip('.')}"


async def _upload_bytes(data: bytes, *, key: str, content_type: str) -> StoredObject:
    try:
        async with get_s3_client() as s3:
            await s3.put_object(
                Bucket=storage_settings.BUCKET,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
    except (BotoCoreError, ClientError) as exc:
        raise StorageError() from exc

    return StoredObject(
        key=key,
    )


async def delete(key: str) -> None:
    """Delete an object. S3 delete is idempotent — deleting a missing key is not an error."""
    try:
        async with get_s3_client() as s3:
            await s3.delete_object(Bucket=storage_settings.BUCKET, Key=key)
    except (BotoCoreError, ClientError) as exc:
        raise StorageError() from exc


async def delete_best_effort(key: str | None) -> None:
    """Delete an object without failing the caller's request if it doesn't go through.

    Used for the previous copy of a replaced profile image: by the time this runs the
    caller's own write (DB commit) has already succeeded, so a storage hiccup here
    shouldn't roll back or fail a request that's otherwise done.
    """
    if key is None:
        return
    with suppress(StorageError):
        await delete(key)


async def delete_if_replaced(old_key: str | None, new_key: str | None) -> None:
    """Best-effort delete `old_key`, but only if a new image actually replaced it."""
    if old_key is not None and old_key != new_key:
        await delete_best_effort(old_key)


@functools.lru_cache(maxsize=1)
def _presign_client():
    """A long-lived sync botocore client used solely to sign URLs.

    Presigning is local HMAC signing with no network I/O, so it needs neither aioboto3
    nor async. Cached because client construction is comparatively expensive. Singleton pattern.
    """
    return botocore.session.get_session().create_client(
        "s3",
        region_name=storage_settings.REGION,
        endpoint_url=storage_settings.ENDPOINT_URL,
        aws_access_key_id=storage_settings.ACCESS_KEY_ID,
        aws_secret_access_key=storage_settings.SECRET_ACCESS_KEY,
        use_ssl=storage_settings.USE_SSL,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def presigned_url(key: str | None, *, expires_in: int | None = None) -> str | None:
    if not key or not storage_settings.is_configured:
        return None
    return _presign_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": storage_settings.BUCKET, "Key": key},
        ExpiresIn=expires_in or storage_settings.PRESIGN_EXPIRY_SECONDS,
    )


async def upload_image(file: UploadFile, *, prefix: str) -> StoredObject:
    """Validate an uploaded image (type + size) and store it under `prefix`."""
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        raise UnsupportedFileType()

    data = await file.read()
    if len(data) > MAX_IMAGE_BYTES:
        raise FileTooLarge()

    key = _build_key(prefix, IMAGE_CONTENT_TYPE_EXTENSIONS[content_type])
    return await _upload_bytes(data, key=key, content_type=content_type)
