"""Validating source URLs and retrieving their bytes."""

from urllib.parse import urlparse

import requests

from datagate_core.errors import FetchError, InvalidURLError

FETCH_TIMEOUT_SECONDS = 15
SUPPORTED_SCHEMES = ("http", "https")


def validate_url(source: str) -> str:
    """Return `source` if it is a fetchable HTTP(S) URL, else raise `InvalidURLError`."""
    try:
        parsed = urlparse(source)
    except ValueError:
        raise InvalidURLError(f"invalid URL: {source!r}")
    if parsed.scheme not in SUPPORTED_SCHEMES or not parsed.netloc:
        raise InvalidURLError(
            f"invalid URL: {source!r} (expected an http:// or https:// address)"
        )
    return source


def fetch(url: str) -> bytes:
    """Download `url`, raising `FetchError` for transport failures and HTTP errors."""
    try:
        response = requests.get(url, timeout=FETCH_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.HTTPError as error:
        raise FetchError(f"remote responded with HTTP {error.response.status_code}")
    except requests.RequestException as error:
        raise FetchError(f"source is unreachable: {error.__class__.__name__}")
    return response.content
