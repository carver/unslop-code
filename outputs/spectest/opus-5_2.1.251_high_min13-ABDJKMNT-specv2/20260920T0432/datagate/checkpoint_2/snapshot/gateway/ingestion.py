"""The /convert pipeline: fetch a remote CSV and turn it into a Dataset."""

from .decoding import decode_bytes
from .sourcing import fetch_source
from .store import Dataset, dataset_id
from .tabular import parse_table


def ingest(source: str, charset: str | None) -> Dataset:
    """Build the dataset for `source`, decoding its bytes with `charset` if given.

    Raises `ApiError` at whichever stage rejects the input.
    """
    text = decode_bytes(fetch_source(source), charset)
    columns, rows = parse_table(text)
    return Dataset(id=dataset_id(source), columns=columns, rows=rows)
