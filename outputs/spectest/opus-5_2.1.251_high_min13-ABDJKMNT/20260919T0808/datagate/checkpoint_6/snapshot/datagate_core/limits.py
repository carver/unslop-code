"""The `MAX_SOURCE_SIZE` ceiling on bytes arriving through `/convert` and `/upload`."""

from datagate_core.errors import SourceTooLargeError


def check_source_size(data: bytes, limit: int | None) -> None:
    """Refuse `data` when it is larger than `limit`.

    A source exactly at the limit is accepted; only one strictly over it is a
    client error, and an unset limit is no maximum at all. What is measured is
    the bytes datagate holds - the downloaded body or the uploaded part - which
    is also what it parses and, for an upload, keys the dataset by (T63).
    """
    if limit is not None and len(data) > limit:
        raise SourceTooLargeError(f"source is {len(data)} bytes, over the {limit}-byte maximum")
