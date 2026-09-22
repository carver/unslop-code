"""The per-request cache control for `/convert`: the `force` flag.

The store itself is the cache — a source already converted is already in it — so
a request only has to say whether it insists on a fresh download. Whether the
process consults the cache at all is the `CACHE_ENABLED` setting, which lives
with the rest of the configuration.
"""

from .errors import ApiError

FORCE = "force"


def forced(args) -> bool:
    """Whether `args` carries the `force` flag, asking to bypass the cache.

    `force` is presence alone: it is given at most once and carries no value,
    so a valued or repeated flag is a bad request whatever the cache setting.
    """
    given = args.getlist(FORCE)
    if not given:
        return False
    if given != [""]:
        raise ApiError(400, f"'{FORCE}' is a flag: give it once, with no value")
    return True
