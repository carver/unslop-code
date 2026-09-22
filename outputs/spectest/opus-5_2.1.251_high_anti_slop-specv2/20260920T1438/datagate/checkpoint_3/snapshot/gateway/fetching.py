"""Validation and retrieval of remote CSV documents."""

from urllib.parse import urlparse

import requests

from gateway.errors import GateError

ALLOWED_SCHEMES = ("http", "https")
REQUEST_TIMEOUT_SECONDS = 20


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
