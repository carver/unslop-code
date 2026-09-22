"""The per-request `force` flag that `/convert` uses to bypass the cache."""

from werkzeug.datastructures import MultiDict

from errors import DatagateError

FORCE_PARAM = "force"


def parse_force(args: MultiDict) -> bool:
    """Read `force`, a presence flag: whatever it is set to, being there at all forces a reparse.

    Giving it twice says nothing more than giving it once does, so it is rejected rather than
    silently collapsed.
    """
    values = args.getlist(FORCE_PARAM)
    if len(values) > 1:
        raise DatagateError(400, f"Repeated query parameter: {FORCE_PARAM!r}")
    return bool(values)
