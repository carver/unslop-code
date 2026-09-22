"""The `MAX_SOURCE_SIZE` ceiling that `/convert` and `/upload` ingest beneath."""

from .errors import DatagateError


def enforce_size(raw, limit):
    """Raise a 400 when `raw` is past `limit`; a payload exactly at it is accepted.

    `limit` is None when the setting is unset, which means no maximum. The bytes
    measured are the file's own, not the transport that carried them
    (AMBIGUITIES T62).
    """
    if limit is not None and len(raw) > limit:
        raise DatagateError(
            400, f"Source is {len(raw)} bytes, over the {limit} byte MAX_SOURCE_SIZE."
        )
