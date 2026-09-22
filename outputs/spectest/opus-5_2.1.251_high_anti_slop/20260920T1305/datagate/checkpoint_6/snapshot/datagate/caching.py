"""The per-request cache bypass for ``/convert``.

Caching lets a repeated conversion of the same source URL answer from the dataset
already stored instead of downloading and parsing the file again. It is governed for
the whole process by the ``CACHE_ENABLED`` setting, and skipped for a single request by
the ``force`` flag.
"""

from werkzeug.datastructures import MultiDict

from .errors import DataGateError


def may_reuse(args: MultiDict[str, str], *, enabled: bool) -> bool:
    """Return whether a stored dataset may answer this ``/convert`` request.

    ``force`` is a presence flag: giving it once, with or without a value, bypasses the
    cache. It is read even when caching is off, so a repeated flag is always a 400.
    """
    forced = args.getlist("force")
    if len(forced) > 1:
        raise DataGateError("query parameter 'force' must not be repeated", 400)
    return enabled and not forced
