"""Cache configuration and the per-request cache bypass.

`/convert` keys its cache on the dataset id, so a repeat of a source URL that
is already stored answers from memory. `CACHE_ENABLED` turns that off for the
whole process, and `force` turns it off for a single request.
"""

import os
from collections.abc import Mapping

from werkzeug.datastructures import MultiDict

from .errors import DataGateError

SETTING = "CACHE_ENABLED"
TRUE_VALUES = ("1", "true", "yes", "on")
FALSE_VALUES = ("0", "false", "no", "off")
FORCE = "force"


class ConfigurationError(Exception):
    """A startup setting the server refuses to run with."""


def caching_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Read `CACHE_ENABLED`, which is read once at startup and defaults to on (T49).

    Matching is case-insensitive but otherwise strict: a value outside the two
    accepted sets -- padding included -- is a configuration error (T50).
    """
    raw = (os.environ if environ is None else environ).get(SETTING)
    if raw is None:
        return True
    value = raw.lower()
    if value in TRUE_VALUES or value in FALSE_VALUES:
        return value in TRUE_VALUES
    accepted = ", ".join(TRUE_VALUES + FALSE_VALUES)
    raise ConfigurationError(f"{SETTING} must be one of {accepted} (case-insensitive), got {raw!r}")


def force_requested(args: MultiDict) -> bool:
    """Read the `force` flag: it may appear at most once, and carries no value.

    An empty `force=` is the same bare flag the browser sends for `force` (T52),
    while a second occurrence is no longer "present once" (T53).
    """
    values = args.getlist(FORCE)
    if len(values) > 1:
        raise DataGateError(f"'{FORCE}' must not be repeated", 400)
    if values and values[0]:
        raise DataGateError(f"'{FORCE}' is a presence flag and takes no value, got {values[0]!r}", 400)
    return bool(values)
