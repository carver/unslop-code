"""Retrieval of the remote CSV bytes named by a ``source`` URL."""

from urllib.parse import urlparse

import requests

from .errors import DataGateError

ALLOWED_SCHEMES = ("http", "https")
REQUEST_TIMEOUT_SECONDS = 15


def fetch_source(url: str) -> bytes:
    """Download ``url`` and return its raw body.

    Raises a 400 error when the URL is not a usable http(s) address and a 404 error
    when the remote host cannot be reached or answers with an HTTP error status.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES or not parsed.netloc:
        raise DataGateError(f"invalid source URL: {url!r}", 400)

    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise DataGateError(f"source is unreachable: {exc}", 404) from exc

    if response.status_code >= 400:
        raise DataGateError(
            f"source responded with HTTP {response.status_code}", 404
        )
    return response.content
