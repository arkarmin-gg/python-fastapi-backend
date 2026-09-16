import uuid
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.dependencies import DbSession
from src.exceptions import InvalidToken
from src.foundation_enums import MembershipStatus, UserStatus
from src.modules.auth import security
from src.modules.auth.exceptions import InactiveUser
from src.modules.memberships.models import OrganizationMembership
from src.modules.users import service as user_service
from src.modules.users.models import User

_bearer = HTTPBearer(auto_error=False)


class CurrentUserContext:
    def __init__(
        self,
        user: User,
        organization_id: uuid.UUID,
        membership_id: uuid.UUID,
    ) -> None:
        self.user = user
        self.organization_id = organization_id
        self.membership_id = membership_id

    @property
    def user_id(self) -> uuid.UUID:
        return self.user.id


async def get_current_user_context(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> CurrentUserContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise InvalidToken()
    token = credentials.credentials
    try:
        payload = security.decode_access_token(token)
        if payload.get("type") != "access":
            raise InvalidToken()
        user_id = uuid.UUID(str(payload["sub"]))
        organization_id = uuid.UUID(str(payload["organization_id"]))
        membership_id = uuid.UUID(str(payload["membership_id"]))
    except Exception as exc:
        raise InvalidToken() from exc

    user = await user_service.get_by_id(db, user_id)
    if user is None:
        raise InvalidToken()
    if user.status != UserStatus.ACTIVE:
        raise InactiveUser()

    membership = await db.get(OrganizationMembership, membership_id)
    if (
        membership is None
        or membership.user_id != user.id
        or membership.organization_id != organization_id
        or membership.status != MembershipStatus.ACTIVE
    ):
        raise InvalidToken()

    return CurrentUserContext(
        user=user,
        organization_id=organization_id,
        membership_id=membership_id,
    )


CurrentUser = Annotated[CurrentUserContext, Depends(get_current_user_context)]
