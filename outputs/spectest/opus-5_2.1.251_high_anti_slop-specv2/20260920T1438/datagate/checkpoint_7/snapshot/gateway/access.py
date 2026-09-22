"""Origin allowlist: which referring sites the service answers at all."""

from urllib.parse import urlsplit

from gateway.errors import GateError


def check_referer(referer: str | None, allowlist: tuple[str, ...]) -> None:
    """Let the request through only when it comes from an allowed site.

    An empty allowlist is no allowlist: every request passes, with or without
    a ``Referer``. Once one is configured the header becomes mandatory, since
    a request that names no origin cannot be shown to come from an allowed one.
    """
    if not allowlist:
        return
    if not referer:
        raise GateError("Request needs a Referer header", 403)

    hostname = urlsplit(referer).hostname
    if hostname is None or not any(covers(suffix, hostname) for suffix in allowlist):
        raise GateError(f"Referer is not allowed: {referer!r}", 403)


def covers(suffix: str, hostname: str) -> bool:
    """Report whether ``suffix`` matches ``hostname`` at a domain boundary.

    ``example.com`` covers itself and ``docs.example.com``, but not
    ``notexample.com``, which merely ends in the same letters.
    """
    hostname = hostname.lower()
    return hostname == suffix or hostname.endswith(f".{suffix}")
