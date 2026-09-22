"""Spec section: Response shape (`_shape`)."""

from tests.conftest import SIMPLE_CSV, TEAMS_CSV, numbered_csv


# Phrase: "`_shape=lists` (default): `rows` is arrays."
def test_default_shape_is_lists(dataset):
    assert dataset(SIMPLE_CSV)["rows"] == [["ada", 36], ["grace", 45]]


# Phrase: "`_shape=lists` (default)" - asking for it explicitly is the same.
def test_explicit_lists_shape_matches_the_default(dataset):
    assert dataset(SIMPLE_CSV, dataset_query="?_shape=lists")["rows"] == [
        ["ada", 36],
        ["grace", 45],
    ]


# Phrase: "`_shape=objects`: `rows` is objects and includes `rowid` (1-based
# source-file row number)."
def test_objects_shape_returns_objects_with_rowid(dataset):
    payload = dataset(SIMPLE_CSV, dataset_query="?_shape=objects")
    assert payload["rows"] == [
        {"rowid": 1, "name": "ada", "age": 36},
        {"rowid": 2, "name": "grace", "age": 45},
    ]


# Phrase: "`rowid` (1-based source-file row number)" - numbering starts at the first
# data row, not at the header line (T16).
def test_rowid_starts_at_one_for_the_first_data_row(dataset):
    payload = dataset(numbered_csv(3), dataset_query="?_shape=objects")
    assert [row["rowid"] for row in payload["rows"]] == [1, 2, 3]


# Phrase: "`rowid` (1-based *source-file* row number)" - it names the source position,
# so pagination does not renumber it.
def test_rowid_follows_the_source_row_through_pagination(dataset):
    payload = dataset(numbered_csv(20), dataset_query="?_shape=objects&_offset=5&_size=2")
    assert [row["rowid"] for row in payload["rows"]] == [6, 7]
    assert [row["n"] for row in payload["rows"]] == [5, 6]


# Phrase: "`rowid` (1-based *source-file* row number)" - sorting does not renumber it.
def test_rowid_follows_the_source_row_through_sorting(dataset):
    payload = dataset(TEAMS_CSV, dataset_query="?_shape=objects&_sort_desc=name")
    assert [(row["rowid"], row["name"]) for row in payload["rows"]] == [
        (2, "grace"),
        (4, "edsger"),
        (3, "alan"),
        (1, "ada"),
    ]


# Phrase: "`rowid` is not in `columns`."
def test_rowid_is_absent_from_columns(dataset):
    payload = dataset(SIMPLE_CSV, dataset_query="?_shape=objects")
    assert payload["columns"] == ["name", "age"]


# Phrase: "`_shape=lists` (default): `rows` is arrays." - lists carry no rowid (T19).
def test_lists_shape_has_no_rowid(dataset):
    assert dataset(SIMPLE_CSV, dataset_query="?_shape=lists")["rows"] == [
        ["ada", 36],
        ["grace", 45],
    ]


# Phrase: "`_shape=objects`" - the other controls still apply to it.
def test_objects_shape_respects_total_and_pagination(dataset):
    payload = dataset(numbered_csv(9), dataset_query="?_shape=objects&_size=2")
    assert payload["total"] == 9 and len(payload["rows"]) == 2


# Phrase: "`_shape` not `lists`/`objects` | 400"
def test_unknown_shape_is_400(endpoint):
    query = endpoint()
    for value in ["arrays", "", "object", "list", "Objects", "LISTS"]:
        response = query(f"?_shape={value}")
        assert response.status_code == 400, value
        assert response.get_json()["ok"] is False
