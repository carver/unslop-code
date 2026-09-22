"""Reading the uploaded file out of a `POST /upload` request."""

from .errors import ApiError

MULTIPART = "multipart/form-data"
# Accepted spellings of the one file field, in precedence order.
FILE_FIELDS = ("file", "attachment")


def uploaded_bytes(request) -> bytes:
    """The bytes of the uploaded file part.

    A request that never claimed to be multipart is an unsupported media type;
    one that claimed it but carries no usable file part — because the body was
    malformed, or simply named the part something else — is a bad request.
    """
    if request.mimetype != MULTIPART:
        raise ApiError(415, f"upload must be a {MULTIPART} request, got '{request.mimetype}'")
    for field in FILE_FIELDS:
        part = request.files.get(field)
        if part is not None:
            return part.read()
    raise ApiError(400, "multipart form carries no 'file' or 'attachment' part")
