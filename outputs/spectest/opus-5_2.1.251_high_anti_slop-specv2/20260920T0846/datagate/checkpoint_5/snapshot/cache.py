"""Cache settings for ``/convert``: the server switch and the per-request flag."""

import os

from errors import ApiError

SETTING = "CACHE_ENABLED"
TRUE_WORDS = ("1", "true", "yes", "on")
FALSE_WORDS = ("0", "false", "no", "off")

FORCE = "force"


def cache_enabled() -> bool:
    """Read the ``CACHE_ENABLED`` environment setting, which defaults to on.

    Only the documented words are accepted, in any capitalisation. Anything
    else is a configuration mistake rather than a request that can be answered,
    so it stops the server from starting.
    """
    setting = os.environ.get(SETTING)
    if setting is None:
        return True
    if setting.lower() in TRUE_WORDS:
        return True
    if setting.lower() in FALSE_WORDS:
        return False
    accepted = ", ".join(TRUE_WORDS + FALSE_WORDS)
    raise ValueError(f"{SETTING} must be one of {accepted}; got {setting!r}")


def force_requested(query_string: str) -> bool:
    """Report whether a conversion request carries the ``force`` flag.

    ``force`` is a presence flag and therefore reads the raw query string:
    ``?force`` bypasses the cache, while carrying a value — an empty one
    included — or repeating the flag is a bad request.
    """
    given = [field for field in query_string.split("&") if field.partition("=")[0] == FORCE]
    if not given:
        return False
    if len(given) > 1:
        raise ApiError(f"Query parameter {FORCE!r} may only be given once", 400)
    if given[0] != FORCE:
        raise ApiError(f"Query parameter {FORCE!r} takes no value", 400)
    return True
