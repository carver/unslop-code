"""The `ORIGIN_ALLOWLIST` gate: which `Referer` headers may reach a route at all."""

from urllib.parse import urlsplit

from .errors import DatagateError


def check_referer(referer, allowlist):
    """Raise a 403 unless `referer` names a host under one of the allowed suffixes.

    An unconfigured allowlist lets every request through. Otherwise a `Referer` is
    required, and one that carries no parseable hostname is refused along with one
    whose host sits outside the list (AMBIGUITIES T66).
    """
    if not allowlist:
        return

    if not referer:
        raise DatagateError(403, "Header 'Referer' is required by the origin allowlist.")

    hostname = urlsplit(referer).hostname
    if hostname is None or not any(_under(hostname, suffix) for suffix in allowlist):
        raise DatagateError(403, f"Referer {referer!r} is not an allowed origin.")


def _under(hostname, suffix):
    """Whether `hostname` is `suffix` itself or a subdomain of it, ignoring case.

    The comparison lands on a label boundary, so `notexample.com` does not count as
    being under `example.com` (AMBIGUITIES T67).
    """
    host = hostname.lower().rstrip(".")
    allowed = suffix.lower()
    return host == allowed or host.endswith(f".{allowed}")
