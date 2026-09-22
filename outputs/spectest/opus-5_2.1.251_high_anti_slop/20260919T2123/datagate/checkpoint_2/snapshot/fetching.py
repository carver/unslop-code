"""Validation and retrieval of remote CSV sources."""

from urllib.parse import urlparse

import requests

from errors import DatagateError

ALLOWED_SCHEMES = ("http", "https")
REQUEST_TIMEOUT_SECONDS = 20


def validate_url(source: str) -> None:
    """Reject anything that is not an absolute http(s) URL with a host."""
    parsed = urlparse(source)
    if parsed.scheme not in ALLOWED_SCHEMES or not parsed.netloc:
        raise DatagateError(400, f"Invalid source URL: {source!r}")


def fetch_bytes(url: str) -> bytes:
    """Download the source, reporting both transport failures and remote errors as 404."""
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise DatagateError(404, f"Source is unreachable: {url}") from exc
    if response.status_code >= 400:
        raise DatagateError(404, f"Source responded with HTTP {response.status_code}")
    return response.content
