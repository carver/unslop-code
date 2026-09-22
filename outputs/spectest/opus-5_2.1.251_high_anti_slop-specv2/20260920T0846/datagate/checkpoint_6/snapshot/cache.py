"""The per-request ``force`` flag of ``/convert``."""

from errors import ApiError

FORCE = "force"


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
