"""The origin allowlist: deciding which requests may reach a route at all."""

from urllib.parse import urlparse

from datagate_core.errors import OriginNotAllowedError

REFERER_HEADER = "Referer"


def check_referer(referer: str | None, allowlist: tuple[str, ...]) -> None:
    """Refuse a request whose `Referer` does not name an allowed domain.

    An unconfigured allowlist lets every request through. Otherwise the header
    is required, and the hostname it parses to must match one of the suffixes;
    a header that is absent is one 403, and one that names an unlisted or
    unparseable origin is the other (T67).
    """
    if not allowlist:
        return
    if referer is None:
        raise OriginNotAllowedError(f"{REFERER_HEADER} header is required")

    hostname = urlparse(referer).hostname
    if hostname is None or not host_allowed(hostname, allowlist):
        raise OriginNotAllowedError(f"{REFERER_HEADER} {referer!r} is not an allowed origin")


def host_allowed(hostname: str, allowlist: tuple[str, ...]) -> bool:
    """Whether `hostname` is, or sits under, any allowed domain suffix.

    Comparison is case-insensitive and stops at label boundaries, so the suffix
    `example.com` covers `example.com` and `a.example.com` but not
    `notexample.com`; a leading or trailing dot on either side is cosmetic (T65).
    """
    host = _domain(hostname)
    return any(
        host == suffix or host.endswith(f".{suffix}") for suffix in map(_domain, allowlist)
    )


def _domain(name: str) -> str:
    """A domain name reduced to the form the boundary comparison uses."""
    return name.strip().strip(".").lower()
