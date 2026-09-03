from collections.abc import Awaitable, Callable

from src.dependencies import DbSession
from src.modules.auth.dependencies import CurrentUser, CurrentUserContext
from src.modules.rbac import service as rbac_service
from src.modules.rbac.exceptions import PermissionDenied


def require_permission(permission_code: str) -> Callable[..., Awaitable[CurrentUserContext]]:
    async def _guard(current: CurrentUser, db: DbSession) -> CurrentUserContext:
        if not await rbac_service.user_has_permission(db, current.user, permission_code):
            raise PermissionDenied()
        return current

    return _guard
