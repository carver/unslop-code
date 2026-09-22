"""Source URL validation and retrieval of the remote CSV bytes."""

from urllib.parse import urlsplit

import requests

from .errors import DatagateError

ALLOWED_SCHEMES = ("http", "https")
TIMEOUT_SECONDS = 15


def validate_source(source):
    """Return `source` if it is an absolute http(s) URL, else raise a 400."""
    if not source:
        raise DatagateError(400, "Query parameter 'source' is required.")

    parts = urlsplit(source)
    if parts.scheme not in ALLOWED_SCHEMES or not parts.netloc:
        raise DatagateError(
            400, f"Invalid URL: 'source' must be an absolute http(s) URL, got {source!r}."
        )
    return source


def fetch_bytes(url):
    """Download `url` and return its body, raising a 404 for any remote failure."""
    try:
        response = requests.get(url, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.content
    except requests.HTTPError as error:
        raise DatagateError(
            404, f"Source returned HTTP {error.response.status_code}: {url}"
        ) from error
    except requests.RequestException as error:
        raise DatagateError(
            404, f"Source unreachable: {url} ({error.__class__.__name__})"
        ) from error
