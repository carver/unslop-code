"""Reading a file out of a multipart upload request."""

import hashlib

from flask import Request

from errors import ApiError

MULTIPART = "multipart/form-data"
FIELDS = ("file", "attachment")


def read_upload(request: Request) -> bytes:
    """Return the bytes of the uploaded file, under either accepted field name.

    A request that is not multipart cannot carry a file at all, which is an
    unsupported media type rather than a bad request. A malformed multipart
    body parses to no fields, so it arrives here as the missing file it
    amounts to.
    """
    if request.mimetype != MULTIPART:
        raise ApiError(f"Uploads must be sent as {MULTIPART}", 415)

    for field in FIELDS:
        uploaded = request.files.get(field)
        if uploaded is not None:
            return uploaded.read()
    raise ApiError(f"Upload needs a {' or '.join(FIELDS)} field", 400)


def upload_origin(payload: bytes) -> str:
    """Identify an upload by its content, so the same bytes keep one endpoint."""
    return f"upload:{hashlib.sha256(payload).hexdigest()}"
