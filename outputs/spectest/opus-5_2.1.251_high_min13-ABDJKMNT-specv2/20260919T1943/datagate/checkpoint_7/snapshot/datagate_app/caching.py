"""What lets `/convert` answer from the store instead of downloading again.

`/convert` keys its cache on the dataset id, so a repeat of a source URL that is
already stored answers from the store. `CACHE_ENABLED` turns that off for the
whole process, and `force` turns it off for a single request.
"""

from werkzeug.datastructures import MultiDict

from .errors import DataGateError
from .parsing import Dataset

FORCE = "force"


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


def cache_serves(cached: Dataset | None, enrich: bool) -> bool:
    """Whether a stored dataset can answer this request as it stands.

    A dataset ingested without enrichment cannot answer `enrich=yes`: the
    metadata has to come from the source bytes, so the request re-ingests and
    upgrades what is stored. An already enriched dataset answers either kind of
    request from the cache, which leaves its stored state untouched.
    """
    return cached is not None and (cached.metadata is not None or not enrich)
