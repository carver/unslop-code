"""The per-request cache bypass.

`/convert` keys its cache on the dataset id, so a repeat of a source URL that is
already stored answers from the store. `CACHE_ENABLED` turns that off for the
whole process, and `force` turns it off for a single request.
"""

from werkzeug.datastructures import MultiDict

from .errors import DataGateError

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
