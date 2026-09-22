"""Cache policy for ``/convert``: the ``CACHE_ENABLED`` setting and its per-request bypass.

Caching lets a repeated conversion of the same source URL answer from the dataset
already in the store instead of downloading and parsing the file again. It is on by
default, turned off for the whole process by ``CACHE_ENABLED``, and skipped for a
single request by the ``force`` flag.
"""

import os

from werkzeug.datastructures import MultiDict

from .errors import DataGateError

SETTING = "CACHE_ENABLED"
TRUE_VALUES = ("1", "true", "yes", "on")
FALSE_VALUES = ("0", "false", "no", "off")


class ConfigError(Exception):
    """A setting the server cannot start with."""


def read_cache_enabled() -> bool:
    """Return whether ``/convert`` may reuse stored datasets, per ``CACHE_ENABLED``.

    The variable is absent by default, which enables caching, and otherwise accepts
    only the documented spellings, case-insensitively. Anything else raises
    ``ConfigError`` so that startup fails rather than guessing.
    """
    raw = os.environ.get(SETTING)
    if raw is None:
        return True

    value = raw.lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False

    accepted = ", ".join(TRUE_VALUES + FALSE_VALUES)
    raise ConfigError(f"{SETTING} must be one of {accepted}; got {raw!r}")


def may_reuse(args: MultiDict[str, str], *, enabled: bool) -> bool:
    """Return whether a stored dataset may answer this ``/convert`` request.

    ``force`` is a presence flag: giving it once, with or without a value, bypasses the
    cache. It is read even when caching is off, so a repeated flag is always a 400.
    """
    forced = args.getlist("force")
    if len(forced) > 1:
        raise DataGateError("query parameter 'force' must not be repeated", 400)
    return enabled and not forced
