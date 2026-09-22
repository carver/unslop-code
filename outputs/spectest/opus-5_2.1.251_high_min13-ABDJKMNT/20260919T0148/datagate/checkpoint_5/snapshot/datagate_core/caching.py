"""Cache policy for `/convert`: the `CACHE_ENABLED` switch and the `force` bypass."""

import os

from .errors import DatagateError

VARIABLE = "CACHE_ENABLED"
TRUE_VALUES = ("1", "true", "yes", "on")
FALSE_VALUES = ("0", "false", "no", "off")
FORCE = "force"


class ConfigurationError(ValueError):
    """An environment value the service refuses to start with."""


def cache_enabled():
    """Whether `/convert` may answer from stored datasets; caching is on by default.

    The vocabulary is strict: only the documented spellings are accepted, and only
    case is folded, so a typo fails startup rather than silently turning caching
    off (AMBIGUITIES T49, T50).
    """
    raw = os.environ.get(VARIABLE)
    if raw is None:
        return True

    value = raw.lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False

    accepted = ", ".join(TRUE_VALUES + FALSE_VALUES)
    raise ConfigurationError(f"{VARIABLE} must be one of {accepted}; got {raw!r}.")


def force_requested(args):
    """True when the presence flag `force` was given; a second one is a 400.

    The flag is about presence, so whatever value it carries is ignored, and the
    duplicate check runs whether or not caching is enabled (AMBIGUITIES T51, T52).
    """
    values = args.getlist(FORCE)
    if len(values) > 1:
        raise DatagateError(400, f"Query parameter '{FORCE}' must not be repeated.")
    return bool(values)
