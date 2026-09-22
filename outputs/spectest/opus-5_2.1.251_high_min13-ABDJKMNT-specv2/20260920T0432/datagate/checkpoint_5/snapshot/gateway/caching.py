"""Cache policy for `/convert`: the `CACHE_ENABLED` setting and the `force` flag.

The store itself is the cache — a source already converted is already in it — so
this module only decides whether a request may be answered from it: once per
process from the environment, and once per request from the query string.
"""

import os

from .errors import ApiError

SETTING = "CACHE_ENABLED"
FORCE = "force"

# The only spellings `CACHE_ENABLED` accepts, matched case-insensitively.
DECISIONS = {
    "1": True,
    "true": True,
    "yes": True,
    "on": True,
    "0": False,
    "false": False,
    "no": False,
    "off": False,
}


class ConfigError(Exception):
    """An unusable setting in the environment: the server must not start."""


def caching_enabled(environ=os.environ) -> bool:
    """Whether `/convert` may answer from the store, per `CACHE_ENABLED`.

    An absent variable is not a value, so it takes the documented default of
    caching enabled. A configured value is matched strictly: case is free, but
    anything else — padding, an empty string, another spelling of a boolean —
    is a configuration error rather than a fallback to the default.
    """
    configured = environ.get(SETTING)
    if configured is None:
        return True
    decision = DECISIONS.get(configured.lower())
    if decision is None:
        raise ConfigError(
            f"{SETTING} must be one of {', '.join(DECISIONS)}, got '{configured}'"
        )
    return decision


def forced(args) -> bool:
    """Whether `args` carries the `force` flag, asking to bypass the cache.

    `force` is presence alone: it is given at most once and carries no value,
    so a valued or repeated flag is a bad request whatever the cache setting.
    """
    given = args.getlist(FORCE)
    if not given:
        return False
    if given != [""]:
        raise ApiError(400, f"'{FORCE}' is a flag: give it once, with no value")
    return True
