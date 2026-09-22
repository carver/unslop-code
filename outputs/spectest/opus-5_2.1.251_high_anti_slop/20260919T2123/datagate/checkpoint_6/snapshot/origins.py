"""The `ORIGIN_ALLOWLIST` check: which requesting sites the service answers at all."""

from urllib.parse import urlparse

from errors import DatagateError

REFERER_HEADER = "Referer"


def check_origin(referer: str | None, allowlist: tuple[str, ...]) -> None:
    """Reject a request whose `Referer` does not sit under one of the allowed domain suffixes.

    An empty allowlist is no allowlist: every request passes, with or without a `Referer`. With
    one configured the header becomes mandatory, since a request that names no origin cannot be
    shown to come from an allowed one.
    """
    if not allowlist:
        return
    if not referer:
        raise DatagateError(403, f"{REFERER_HEADER} header is required")
    hostname = urlparse(referer).hostname
    if hostname is None or not any(_under(hostname, suffix) for suffix in allowlist):
        raise DatagateError(403, f"{REFERER_HEADER} is not from an allowed origin: {referer!r}")


def _under(hostname: str, suffix: str) -> bool:
    """Whether a hostname is the allowed domain itself or a subdomain of it.

    Matching stops at a label boundary, so `example.com` covers `docs.example.com` but neither
    `notexample.com` nor `example.com.elsewhere.org`. `urlparse` has already lowercased the
    hostname and the suffixes were lowercased when they were read.
    """
    return hostname == suffix or hostname.endswith(f".{suffix}")
