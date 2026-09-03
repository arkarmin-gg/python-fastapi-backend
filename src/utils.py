import re
import secrets
import unicodedata
from collections.abc import Awaitable, Callable
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_SLUG_MAX_LENGTH = 100
DEFAULT_SLUG_MAX_ATTEMPTS = 100


def normalize_email(value: str) -> str:
    return value.strip().lower()


def iso_or_none(value: datetime | None) -> str | None:
    """Render a nullable timestamp for an activity-log old_value/new_value snapshot."""
    return value.isoformat() if value else None


def generate_temporary_password(byte_length: int = 9) -> str:
    return secrets.token_urlsafe(byte_length)


def ensure_iana_timezone(value: str) -> None:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("Timezone must be a valid IANA timezone name.") from exc


def slugify(
    value: str,
    *,
    fallback_prefix: str,
    max_length: int = DEFAULT_SLUG_MAX_LENGTH,
) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")
    fallback = f"{fallback_prefix}-{secrets.token_hex(3)}"
    return slug[:max_length].strip("-") or fallback


def with_slug_suffix(base_slug: str, attempt: int, *, max_length: int) -> str:
    if attempt == 0:
        return base_slug[:max_length].strip("-")
    suffix = f"-{attempt + 1}"
    return f"{base_slug[: max_length - len(suffix)].strip('-')}{suffix}"


async def generate_unique_slug(
    value: str,
    *,
    fallback_prefix: str,
    exists: Callable[[str], Awaitable[bool]],
    max_length: int = DEFAULT_SLUG_MAX_LENGTH,
    max_attempts: int = DEFAULT_SLUG_MAX_ATTEMPTS,
) -> str | None:
    base_slug = slugify(value, fallback_prefix=fallback_prefix, max_length=max_length)
    for attempt in range(max_attempts):
        candidate = with_slug_suffix(base_slug, attempt, max_length=max_length)
        if not await exists(candidate):
            return candidate
    return None
