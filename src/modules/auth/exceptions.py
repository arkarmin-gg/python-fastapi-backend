from fastapi import status

from src.exceptions import AppException


class InactiveUser(AppException):
    status_code = status.HTTP_403_FORBIDDEN
    error_code = "inactive_user"
    detail = "User is inactive or locked."
