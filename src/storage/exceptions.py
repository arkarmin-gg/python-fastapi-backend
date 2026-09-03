from fastapi import status

from src.exceptions import AppException


class StorageError(AppException):
    """The object store itself failed (network, credentials, bucket missing, ...)."""

    status_code = status.HTTP_502_BAD_GATEWAY
    error_code = "storage_error"
    detail = "Object storage operation failed."


class StorageNotConfigured(AppException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = "storage_not_configured"
    detail = "File storage is not configured on this server."


class UnsupportedFileType(AppException):
    status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    error_code = "unsupported_file_type"
    detail = "This file type is not allowed."


class FileTooLarge(AppException):
    status_code = status.HTTP_413_CONTENT_TOO_LARGE
    error_code = "file_too_large"
    detail = "The uploaded file is too large."
