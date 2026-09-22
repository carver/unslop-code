"""Validating and downloading the remote CSV named by `source`."""

from urllib.parse import urlsplit

import requests

from .errors import ApiError

FETCH_TIMEOUT_SECONDS = 15
SUPPORTED_SCHEMES = ("http", "https")


def fetch_source(url: str) -> bytes:
    """Return the bytes served at `url`.

    A URL that is not a fetchable http(s) address is a caller mistake (400);
    a host that will not answer, or answers with an error status, is a 404.
    """
    _validate_url(url)
    try:
        response = requests.get(url, timeout=FETCH_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise ApiError(404, f"source could not be reached: {exc}") from exc
    if not response.ok:
        raise ApiError(404, f"source returned HTTP {response.status_code}")
    return response.content


def _validate_url(url: str) -> None:
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise ApiError(400, f"invalid source URL: {exc}") from exc
    if parts.scheme not in SUPPORTED_SCHEMES:
        raise ApiError(400, f"source URL must use http or https, got '{parts.scheme}'")
    if not parts.hostname:
        raise ApiError(400, "source URL is missing a host")
