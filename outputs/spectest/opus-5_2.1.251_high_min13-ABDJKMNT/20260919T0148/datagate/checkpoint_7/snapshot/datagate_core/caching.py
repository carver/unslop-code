"""The `force` bypass that re-ingests a `/convert` source regardless of the cache."""

from .errors import DatagateError

FORCE = "force"


def force_requested(args):
    """True when the presence flag `force` was given; a second one is a 400.

    The flag is about presence, so whatever value it carries is ignored, and the
    duplicate check runs whether or not caching is enabled (AMBIGUITIES T51, T52).
    """
    values = args.getlist(FORCE)
    if len(values) > 1:
        raise DatagateError(400, f"Query parameter '{FORCE}' must not be repeated.")
    return bool(values)
