"""Spec section: `total`."""

from tests.conftest import SIMPLE_CSV, numbered_csv


# Phrase: "Responses include integer `total` ..."
def test_total_is_an_integer_on_every_dataset_response(dataset):
    payload = dataset(SIMPLE_CSV)
    assert payload["total"] == 2
    assert isinstance(payload["total"], int) and not isinstance(payload["total"], bool)


# Phrase: "... `total` for the row count before pagination." - the default 100-row page
# does not shrink it.
def test_total_counts_all_rows_not_the_returned_page(dataset):
    payload = dataset(numbered_csv(250))
    assert payload["total"] == 250
    assert len(payload["rows"]) == 100


# Phrase: "... the row count before pagination." - explicit `_size`/`_offset` too.
def test_total_ignores_size_and_offset(dataset):
    payload = dataset(numbered_csv(40), dataset_query="?_size=5&_offset=30")
    assert payload["total"] == 40
    assert len(payload["rows"]) == 5


# Phrase: "the row count" - rows, not including the header row.
def test_total_excludes_the_header_row(dataset):
    assert dataset(numbered_csv(3))["total"] == 3


# Phrase: "Responses include integer `total`" - alongside the existing envelope keys.
def test_total_joins_the_existing_payload_keys(dataset):
    assert set(dataset(SIMPLE_CSV)) == {"ok", "columns", "rows", "query_ms", "total"}


# Phrase: "Responses include integer `total`" - scoped to the dataset endpoint (T24).
def test_convert_response_is_unchanged(convert):
    assert set(convert(SIMPLE_CSV).get_json()) == {"ok", "endpoint"}
