"""Cache configuration and the per-request control that bypasses the cache."""

import os

from gateway.errors import GateError

#: Environment variable switching the ``/convert`` cache on or off.
CACHE_SETTING = "CACHE_ENABLED"
TRUE_WORDS = ("1", "true", "yes", "on")
FALSE_WORDS = ("0", "false", "no", "off")

#: Query parameter forcing one ``/convert`` request past the cache.
FORCE = "force"


class ConfigurationError(Exception):
    """A setting in the environment is unreadable, so the service must not start."""


def cache_enabled() -> bool:
    """Read :data:`CACHE_SETTING`, which is on unless it is set to a false word.

    Only the listed words are understood, in any mix of upper and lower case;
    anything else -- including a value padded with spaces -- is a typo rather
    than an intention, and stops the service before it serves a request under
    the wrong caching policy.
    """
    raw = os.environ.get(CACHE_SETTING)
    if raw is None:
        return True

    word = raw.lower()
    if word in TRUE_WORDS:
        return True
    if word in FALSE_WORDS:
        return False
    raise ConfigurationError(
        f"{CACHE_SETTING} must be one of "
        f"{', '.join(TRUE_WORDS + FALSE_WORDS)}, not {raw!r}"
    )


def force_requested(query_string: bytes) -> bool:
    """Report whether the request carries the bare ``force`` flag.

    ``force`` says only that it is there, so it is read from the raw query
    string: Flask reports ``?force`` and ``?force=yes`` as the same key with
    the same empty value, and only the second is a 400.
    """
    occurrences = [
        parameter
        for parameter in query_string.decode("utf-8", "replace").split("&")
        if parameter.split("=", 1)[0] == FORCE
    ]
    if not occurrences:
        return False
    if len(occurrences) > 1:
        raise GateError(f"Query parameter {FORCE!r} may be given only once", 400)
    if "=" in occurrences[0]:
        raise GateError(f"Query parameter {FORCE!r} takes no value", 400)
    return True
