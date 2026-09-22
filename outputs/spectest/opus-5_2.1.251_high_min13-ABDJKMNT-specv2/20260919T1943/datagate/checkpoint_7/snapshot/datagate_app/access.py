"""The origin allowlist: which referring sites may reach the service at all.

The check runs before routing, so a request from an unlisted origin is refused
whether or not the path it asked for exists (T66).
"""

from urllib.parse import urlparse

from .errors import DataGateError


def enforce_allowlist(referer: str | None, allowlist: tuple[str, ...]) -> None:
    """Refuse a request whose `Referer` is missing or off `allowlist`.

    An unconfigured allowlist lets everything through, including requests that
    carry no `Referer` at all.
    """
    if not allowlist:
        return
    if not referer:
        raise DataGateError("The origin allowlist requires a Referer header", 403)
    hostname = urlparse(referer).hostname
    if not hostname or not any(_matches(hostname, suffix) for suffix in allowlist):
        raise DataGateError(f"Referer {referer!r} is not on the origin allowlist", 403)


def _matches(hostname: str, suffix: str) -> bool:
    """Compare on label boundaries: the suffix is the whole host or a parent of it.

    Both sides are lower-cased, a fully qualified trailing dot is dropped and a
    leading dot on the configured suffix is optional (T62), so `example.com`
    covers `app.example.com` but never `notexample.com`.
    """
    host = hostname.rstrip(".").lower()
    allowed = suffix.strip(".").lower()
    return host == allowed or host.endswith(f".{allowed}")
