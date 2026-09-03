import uuid
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer

from src.config import settings
from src.dependencies import DbSession
from src.exceptions import InvalidToken
from src.foundation_enums import UserStatus
from src.modules.auth import security
from src.modules.auth.exceptions import InactiveUser
from src.modules.users import service as user_service
from src.modules.users.models import User

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_PREFIX}/auth/login",
    scheme_name="Bearer",
)


@dataclass(frozen=True)
class CurrentUserContext:
    user: User
    tenant_id: uuid.UUID

    @property
    def user_id(self) -> uuid.UUID:
        return self.user.id


async def get_current_user_context(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: DbSession,
) -> CurrentUserContext:
    try:
        payload = security.decode_access_token(token)
    except jwt.InvalidTokenError as exc:
        raise InvalidToken() from exc

    if payload.get("type") != "access":
        raise InvalidToken()

    try:
        user_id = uuid.UUID(str(payload["sub"]))
        tenant_id = uuid.UUID(str(payload["tenant_id"]))
    except (KeyError, ValueError) as exc:
        raise InvalidToken() from exc

    user = await user_service.get_by_id(db, tenant_id, user_id)
    if user is None:
        raise InvalidToken()
    if user.status != UserStatus.ACTIVE:
        raise InactiveUser()
    return CurrentUserContext(user=user, tenant_id=tenant_id)


CurrentUser = Annotated[CurrentUserContext, Depends(get_current_user_context)]
