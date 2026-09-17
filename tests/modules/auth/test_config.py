import pytest
from pydantic import ValidationError
from src.config import Environment, Settings
from src.modules.auth.config import AuthSettings


def test_auth_settings_load_documented_env_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "a" * 48
    monkeypatch.setenv("AUTH_JWT_SECRET", secret)

    settings = AuthSettings(_env_file=None)

    assert secret == settings.JWT_SECRET


def test_auth_settings_require_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUTH_JWT_SECRET", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)

    with pytest.raises(ValidationError):
        AuthSettings(_env_file=None)


def test_production_rejects_wildcard_cors() -> None:
    with pytest.raises(ValidationError, match="CORS_ORIGINS cannot contain"):
        Settings(
            DATABASE_URL="postgresql://postgres:postgres@localhost/test",
            ENVIRONMENT=Environment.PRODUCTION,
            CORS_ORIGINS=["*"],
            _env_file=None,
        )
