"""The origin allowlist: which requests are allowed to reach the routes."""

from urllib.parse import urlsplit

from .errors import ApiError


def check_origin(referer: str | None, allowed: tuple[str, ...]) -> None:
    """Refuse a request whose `Referer` is missing or off the allowlist.

    No allowlist means no check at all, so an unconfigured service never asks
    callers for a `Referer`.
    """
    if not allowed:
        return
    if not referer:
        raise ApiError(403, "a Referer header is required by the origin allowlist")
    hostname = urlsplit(referer).hostname
    if hostname is None or not _is_allowed(hostname, allowed):
        raise ApiError(403, f"referer '{referer}' is not on the origin allowlist")


def _is_allowed(hostname: str, allowed: tuple[str, ...]) -> bool:
    """Whether `hostname` is an allowed domain or sits under one.

    Matching runs on whole labels, so `example.com` covers `app.example.com`
    but neither `notexample.com` nor `example.com.elsewhere.net`.
    """
    host = hostname.lower().rstrip(".")
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in allowed)
