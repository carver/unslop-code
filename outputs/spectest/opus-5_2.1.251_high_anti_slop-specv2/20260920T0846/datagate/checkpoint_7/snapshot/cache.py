"""What ``/convert`` serves from the store and what it reads again."""

from errors import ApiError
from store import Dataset

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


def reingest_needed(stored: Dataset | None, forced: bool, enriching: bool, cached: bool) -> bool:
    """Decide whether a conversion has to read its source again.

    A source nobody has converted yet, a forced request and a disabled cache
    all send the conversion back to the source. So does a request for
    enrichment over a dataset stored without it, which upgrades what is stored
    rather than answering from it; a stored dataset that already carries
    metadata satisfies such a request as it is.
    """
    if stored is None or forced or not cached:
        return True
    return enriching and stored.metadata is None
