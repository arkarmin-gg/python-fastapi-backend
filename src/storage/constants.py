IMAGE_CONTENT_TYPE_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}

ALLOWED_IMAGE_CONTENT_TYPES = frozenset(IMAGE_CONTENT_TYPE_EXTENSIONS)

MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MiB
