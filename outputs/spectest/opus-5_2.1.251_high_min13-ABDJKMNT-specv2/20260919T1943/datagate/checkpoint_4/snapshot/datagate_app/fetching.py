"""Fetching the document named by the `source` parameter."""

from urllib.parse import urlparse

import requests

from .errors import DataGateError
from .formats import SourceDocument

REQUEST_TIMEOUT_SECONDS = 15
ALLOWED_SCHEMES = ("http", "https")


def validate_url(source: str) -> str:
    """Reject anything that is not an absolute http(s) URL."""
    parsed = urlparse(source)
    if parsed.scheme not in ALLOWED_SCHEMES or not parsed.netloc:
        raise DataGateError(f"Invalid source URL: {source!r}", 400)
    return source


def fetch_source(source: str) -> SourceDocument:
    """Download `source`, reporting every remote-side failure as a 404."""
    validate_url(source)
    try:
        response = requests.get(source, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise DataGateError(f"Source unreachable: {exc}", 404) from None
    if response.status_code >= 400:
        raise DataGateError(f"Source returned HTTP {response.status_code}", 404)
    return SourceDocument(response.content, response.headers.get("Content-Type", ""))
