"""The `/convert` pipeline: fetch, decode, parse."""

from .fetching import fetch_source
from .decoding import decode_document
from .parsing import Dataset, parse_table, reject_non_tabular


def build_dataset(source: str, charset: str | None = None) -> Dataset:
    """Download `source` and turn it into a `Dataset`."""
    document = fetch_source(source)
    text = decode_document(document.data, charset)
    reject_non_tabular(document.content_type, text)
    return parse_table(text)
