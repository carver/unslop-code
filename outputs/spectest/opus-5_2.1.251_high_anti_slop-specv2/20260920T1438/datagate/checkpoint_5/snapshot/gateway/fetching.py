"""Obtaining raw payloads: remote downloads and uploaded files."""

from urllib.parse import urlparse

import requests
from werkzeug.wrappers import Request

from gateway.errors import GateError

ALLOWED_SCHEMES = ("http", "https")
REQUEST_TIMEOUT_SECONDS = 20
MULTIPART = "multipart/form-data"
#: Form fields an upload may carry its file in.
UPLOAD_FIELDS = ("file", "attachment")


def validate_source(source: str) -> None:
    """Reject anything that is not an absolute http(s) URL."""
    parsed = urlparse(source)
    if parsed.scheme not in ALLOWED_SCHEMES or not parsed.netloc:
        raise GateError(f"Invalid source URL: {source!r}", 400)


def fetch(source: str) -> bytes:
    """Download ``source`` and return its raw bytes.

    Transport failures and remote error statuses are both reported as 404:
    from the caller's point of view the dataset could not be located.
    """
    try:
        response = requests.get(source, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise GateError(f"Source unreachable: {exc}", 404) from exc

    if response.status_code >= 400:
        raise GateError(
            f"Source responded with HTTP {response.status_code}", 404
        )
    return response.content


def read_upload(request: Request) -> bytes:
    """Return the bytes of the file a ``POST /upload`` request carries.

    A body that is not a multipart form cannot hold a file at all, which is a
    media type the endpoint does not support. A multipart body that is
    malformed parses into no fields, and is reported like one that simply
    named no file.
    """
    if request.mimetype != MULTIPART:
        raise GateError(f"Upload must be sent as {MULTIPART}", 415)

    for field in UPLOAD_FIELDS:
        upload = request.files.get(field)
        if upload is not None:
            return upload.read()
    raise GateError(
        f"Upload needs a file in one of the fields: {', '.join(UPLOAD_FIELDS)}", 400
    )
