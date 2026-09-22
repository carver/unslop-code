"""The ingestion pipeline: URL in, stored dataset out."""

from .decoding import decode_csv_bytes
from .fetching import fetch_bytes, validate_source
from .inference import coerce_value
from .parsing import parse_table
from .store import Dataset, dataset_id


def convert_source(source, charset, store):
    """Fetch, decode, parse and store `source`, returning its dataset id."""
    url = validate_source(source)
    text = decode_csv_bytes(fetch_bytes(url), charset)
    columns, rows = parse_table(text)

    identifier = dataset_id(url)
    store.put(identifier, Dataset(columns, [[coerce_value(cell) for cell in row] for row in rows]))
    return identifier
