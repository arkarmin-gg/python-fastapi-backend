from fastapi import APIRouter, status

from src.dependencies import DbSession
from src.exceptions import InvalidCredentials, InvalidCurrentPassword, InvalidToken
from src.modules.auth import service
from src.modules.auth.dependencies import CurrentUser
from src.modules.auth.exceptions import InactiveUser
from src.modules.auth.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
)
from src.modules.users import service as user_service
from src.modules.users.schemas import UserProfileUpdate, UserRead
from src.schemas import error_responses

router = APIRouter(prefix="/auth", tags=["Auth"])

_AUTH_ERRORS = (InvalidToken, InactiveUser)


@router.post(
    "/login",
    response_model=TokenResponse,
    responses=error_responses(InvalidCredentials, InactiveUser),
)
async def login(body: LoginRequest, db: DbSession) -> TokenResponse:
    access_token, refresh_token = await service.login(
        db,
        organization_id=body.organization_id,
        organization_code=body.organization_code,
        identifier=body.identifier,
        password=body.password,
    )
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse, responses=error_responses(InvalidToken))
async def refresh(body: RefreshRequest, db: DbSession) -> TokenResponse:
    access_token, refresh_token = await service.rotate_refresh_token(
        db,
        body.refresh_token,
        organization_id=body.organization_id,
        organization_code=body.organization_code,
    )
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    responses=error_responses(*_AUTH_ERRORS),
)
async def logout(current: CurrentUser, db: DbSession) -> None:
    await service.logout(
        db,
        current.user,
        organization_id=current.organization_id,
        membership_id=current.membership_id,
    )


@router.get("/me", response_model=UserRead, responses=error_responses(*_AUTH_ERRORS))
async def me(current: CurrentUser, db: DbSession):
    user = await user_service.get_by_id(db, current.user_id)
    assert user is not None
    await db.refresh(user)
    return user


@router.patch("/me", response_model=UserRead, responses=error_responses(*_AUTH_ERRORS))
async def update_me(current: CurrentUser, db: DbSession, body: UserProfileUpdate):
    return await user_service.update_profile(db, current.user_id, body)


@router.patch(
    "/me/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    responses=error_responses(*_AUTH_ERRORS, InvalidCurrentPassword),
)
async def change_my_password(
    current: CurrentUser,
    db: DbSession,
    body: ChangePasswordRequest,
) -> None:
    await service.change_password(
        db,
        current.user,
        current_password=body.current_password,
        new_password=body.new_password,
        organization_id=current.organization_id,
        membership_id=current.membership_id,
    )
