import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from src.modules.auth.config import auth_settings

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    return True


def create_access_token(user_id: str, organization_id: str, membership_id: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "organization_id": organization_id,
        "membership_id": membership_id,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=auth_settings.JWT_ACCESS_EXP_MINUTES),
    }
    return jwt.encode(payload, auth_settings.JWT_SECRET, algorithm=auth_settings.JWT_ALG)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, auth_settings.JWT_SECRET, algorithms=[auth_settings.JWT_ALG])


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()
