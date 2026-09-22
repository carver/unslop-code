"""Cache controls for `/convert`: the `CACHE_ENABLED` setting and the per-request `force` flag."""

import os

from werkzeug.datastructures import MultiDict

from errors import DatagateError

CACHE_ENABLED_VAR = "CACHE_ENABLED"
FORCE_PARAM = "force"
TRUE_VALUES = ("1", "true", "yes", "on")
FALSE_VALUES = ("0", "false", "no", "off")


def cache_enabled_from_env() -> bool:
    """Read `CACHE_ENABLED`, which is on unless it is set to one of the recognised false values.

    Only the documented spellings are accepted, case aside; anything else is a configuration
    mistake rather than a default to fall back on, so it raises and the service refuses to start.
    """
    raw = os.environ.get(CACHE_ENABLED_VAR)
    if raw is None:
        return True
    value = raw.lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    accepted = ", ".join(TRUE_VALUES + FALSE_VALUES)
    raise ValueError(f"{CACHE_ENABLED_VAR} must be one of {accepted}, got {raw!r}")


def parse_force(args: MultiDict) -> bool:
    """Read `force`, a presence flag: whatever it is set to, being there at all forces a reparse.

    Giving it twice says nothing more than giving it once does, so it is rejected rather than
    silently collapsed.
    """
    values = args.getlist(FORCE_PARAM)
    if len(values) > 1:
        raise DatagateError(400, f"Repeated query parameter: {FORCE_PARAM!r}")
    return bool(values)
