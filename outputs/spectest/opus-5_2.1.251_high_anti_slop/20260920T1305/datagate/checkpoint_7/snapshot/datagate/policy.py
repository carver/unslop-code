"""Checks a request must pass before it is served: its origin and its source's size."""

from urllib.parse import urlparse

from .errors import DataGateError


def check_origin(referer: str | None, allowlist: tuple[str, ...]) -> None:
    """Reject a request whose ``Referer`` names a host outside ``allowlist``.

    An empty allowlist accepts every request. Otherwise the request must carry a
    ``Referer`` whose hostname is one of the allowed domains or a subdomain of one --
    ``app.example.com`` passes for ``example.com`` while ``notexample.com`` does not --
    and a request that is not raises a 403 error.
    """
    if not allowlist:
        return

    if not referer:
        raise DataGateError("Referer header is required", 403)

    hostname = urlparse(referer).hostname
    if hostname is None or not any(_covers(suffix, hostname) for suffix in allowlist):
        raise DataGateError(f"origin {referer!r} is not allowed", 403)


def check_source_size(size: int, limit: int | None) -> None:
    """Reject a source over ``MAX_SOURCE_SIZE`` bytes; one of exactly that size passes."""
    if limit is not None and size > limit:
        raise DataGateError(
            f"source is {size} bytes, above the {limit} byte limit", 400
        )


def _covers(suffix: str, hostname: str) -> bool:
    """Return whether an allowed suffix covers a hostname, on domain boundaries only.

    ``urlparse`` lowercases the hostname and the suffixes are lowercased as they are
    read, so the comparison is case-insensitive.
    """
    return hostname == suffix or hostname.endswith(f".{suffix}")
