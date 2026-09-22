"""The per-request `force` cache-bypass flag. Whether the cache is on is a setting."""

from werkzeug.datastructures import MultiDict

from datagate_core.errors import InvalidRequestError

FORCE_PARAMETER = "force"


def is_forced(args: MultiDict) -> bool:
    """Whether this request carries the `force` bypass flag.

    `force` is a presence flag, so its value is never read (T51); a second
    occurrence is a client error whether or not caching is on (T53).
    """
    given = args.getlist(FORCE_PARAMETER)
    if len(given) > 1:
        raise InvalidRequestError(f"query parameter {FORCE_PARAMETER!r} must not be repeated")
    return bool(given)
