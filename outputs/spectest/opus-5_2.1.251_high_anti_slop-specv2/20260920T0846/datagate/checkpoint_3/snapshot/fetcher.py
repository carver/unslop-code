"""Validation and retrieval of remote CSV sources."""

from urllib.parse import urlparse

import requests

from errors import ApiError

ALLOWED_SCHEMES = ("http", "https")
REQUEST_TIMEOUT_SECONDS = 15


def validate_source(url: str) -> str:
    """Reject anything that is not an absolute http(s) URL."""
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES or not parsed.netloc:
        raise ApiError(f"Invalid source URL: {url!r}", 400)
    return url


def fetch(url: str) -> bytes:
    """Download the raw bytes served at ``url``.

    Transport failures and remote error statuses both surface as 404: from the
    caller's point of view the requested source could not be retrieved.
    """
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise ApiError(f"Source unreachable: {url}", 404) from exc
    if response.status_code >= 400:
        raise ApiError(f"Source returned HTTP {response.status_code}: {url}", 404)
    return response.content
