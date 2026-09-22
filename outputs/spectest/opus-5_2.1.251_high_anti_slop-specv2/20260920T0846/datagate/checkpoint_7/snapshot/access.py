"""Configured limits a request has to clear: its origin and its source size."""

from urllib.parse import urlparse

from errors import ApiError


def check_origin(referer: str | None, allowlist: tuple[str, ...]) -> None:
    """Reject a request whose ``Referer`` names no allowed origin.

    An empty allowlist lets every request through. A configured one makes the
    header mandatory, since a request without it names no origin to judge.
    """
    if not allowlist:
        return
    if not referer:
        raise ApiError("A Referer header naming an allowed origin is required", 403)

    hostname = urlparse(referer).hostname
    if hostname is None or not any(_covers(suffix, hostname) for suffix in allowlist):
        raise ApiError(f"Referer {referer!r} is not an allowed origin", 403)


def _covers(suffix: str, hostname: str) -> bool:
    """Report whether a suffix covers a hostname, label by label.

    ``example.com`` covers itself and ``eu.example.com`` but not
    ``notexample.com``: a suffix always starts at a domain boundary.
    ``urlparse`` has already lowercased the hostname.
    """
    suffix = suffix.strip(".").lower()
    return hostname == suffix or hostname.endswith(f".{suffix}")


def check_size(payload: bytes, limit: int | None) -> None:
    """Reject a source past the configured maximum, which is itself allowed."""
    if limit is not None and len(payload) > limit:
        raise ApiError(f"Source is {len(payload)} bytes, over the {limit} byte limit", 400)
