"""Cache configuration (`CACHE_ENABLED`) and the per-request `force` bypass."""

import os

from werkzeug.datastructures import MultiDict

from datagate_core.errors import InvalidRequestError

#: Environment variable that switches `/convert`'s dataset cache on or off.
CACHE_SETTING = "CACHE_ENABLED"
FORCE_PARAMETER = "force"

#: The only spellings `CACHE_ENABLED` accepts, compared case-insensitively.
TRUE_VALUES = ("1", "true", "yes", "on")
FALSE_VALUES = ("0", "false", "no", "off")


class ConfigurationError(Exception):
    """A startup setting holds a value datagate refuses to guess the meaning of."""


def cache_enabled(environ: dict[str, str] | None = None) -> bool:
    """Read `CACHE_ENABLED`; caching is on unless the setting spells out a false value.

    Only the listed spellings are accepted, in any case but with no surrounding
    whitespace (T50); anything else fails startup (T49).
    """
    raw = (environ if environ is not None else os.environ).get(CACHE_SETTING)
    if raw is None:
        return True
    setting = raw.lower()
    if setting in TRUE_VALUES:
        return True
    if setting in FALSE_VALUES:
        return False
    raise ConfigurationError(
        f"{CACHE_SETTING} must be one of {', '.join(TRUE_VALUES + FALSE_VALUES)}, got {raw!r}"
    )


def is_forced(args: MultiDict) -> bool:
    """Whether this request carries the `force` bypass flag.

    `force` is a presence flag, so its value is never read (T51); a second
    occurrence is a client error whether or not caching is on (T53).
    """
    given = args.getlist(FORCE_PARAMETER)
    if len(given) > 1:
        raise InvalidRequestError(f"query parameter {FORCE_PARAMETER!r} must not be repeated")
    return bool(given)
