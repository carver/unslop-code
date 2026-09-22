"""The `MAX_SOURCE_SIZE` check applied to everything the service ingests."""

from errors import DatagateError


def check_source_size(size: int, limit: int | None) -> None:
    """Reject a source larger than the configured limit; a source exactly at it is accepted.

    An unset limit means there is no maximum.
    """
    if limit is not None and size > limit:
        raise DatagateError(400, f"Source is {size} bytes, above the {limit} byte limit")
