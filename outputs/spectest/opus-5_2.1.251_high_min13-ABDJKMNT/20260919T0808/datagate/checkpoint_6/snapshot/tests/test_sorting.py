"""Spec section: Sorting (`_sort`, `_sort_desc`)."""

from tests.conftest import TEAMS_CSV, numbered_csv

MIXED_CSV = "label,value\na,10\nb,2\nc,apple\nd,\ne,-3\n"


def names(payload):
    return [row[0] for row in payload["rows"]]


# Phrase: "`_sort=<column>` sorts ascending by `<column>`."
def test_sort_orders_ascending(dataset):
    payload = dataset(TEAMS_CSV, dataset_query="?_sort=name")
    assert names(payload) == ["ada", "alan", "edsger", "grace"]


# Phrase: "`_sort=<column>` sorts ascending" - numeric columns compare as numbers.
def test_sort_on_a_numeric_column_is_numeric(dataset):
    body = "n,tag\n2,b\n10,a\n1,c\n"
    payload = dataset(body, dataset_query="?_sort=n")
    assert [row[0] for row in payload["rows"]] == [1, 2, 10]


# Phrase: "`_sort_desc=<column>` sorts descending by `<column>`."
def test_sort_desc_orders_descending(dataset):
    payload = dataset(TEAMS_CSV, dataset_query="?_sort_desc=name")
    assert names(payload) == ["grace", "edsger", "alan", "ada"]


# Phrase: "If both are present, `_sort_desc` wins."
def test_sort_desc_wins_over_sort(dataset):
    payload = dataset(TEAMS_CSV, dataset_query="?_sort=age&_sort_desc=name")
    assert names(payload) == ["grace", "edsger", "alan", "ada"]


# Phrase: "If both are present, `_sort_desc` wins." - order in the query string is
# irrelevant.
def test_sort_desc_wins_regardless_of_parameter_order(dataset):
    payload = dataset(TEAMS_CSV, dataset_query="?_sort_desc=name&_sort=age")
    assert names(payload) == ["grace", "edsger", "alan", "ada"]


# Phrase: "Sorting is stable" - tied rows keep their source order.
def test_ascending_sort_is_stable(dataset):
    payload = dataset(TEAMS_CSV, dataset_query="?_sort=team")
    assert names(payload) == ["ada", "alan", "grace", "edsger"]


# Phrase: "Sorting is stable" - descending too: ties are not reversed.
def test_descending_sort_is_stable(dataset):
    payload = dataset(TEAMS_CSV, dataset_query="?_sort_desc=team")
    assert names(payload) == ["grace", "edsger", "ada", "alan"]


# Phrase: "Sorting is stable and applied before pagination."
def test_sorting_happens_before_pagination(dataset):
    payload = dataset(numbered_csv(20), dataset_query="?_sort_desc=n&_size=3")
    assert [row[0] for row in payload["rows"]] == [19, 18, 17]


# Phrase: "... applied before pagination." - `_offset` walks the sorted rows.
def test_offset_applies_to_the_sorted_rows(dataset):
    payload = dataset(numbered_csv(20), dataset_query="?_sort_desc=n&_offset=2&_size=2")
    assert [row[0] for row in payload["rows"]] == [17, 16]


# Phrase: "... applied before pagination." - `total` still counts every row.
def test_total_is_unaffected_by_sorting(dataset):
    assert dataset(numbered_csv(20), dataset_query="?_sort=n&_size=2")["total"] == 20


# Phrase: "Empty values ... return `HTTP 400`."
def test_empty_sort_value_is_400(endpoint):
    query = endpoint(TEAMS_CSV)
    for parameter in ["_sort", "_sort_desc"]:
        response = query(f"?{parameter}=")
        assert response.status_code == 400, parameter
        assert response.get_json()["ok"] is False


# Phrase: "... or unknown columns return `HTTP 400`."
def test_unknown_sort_column_is_400(endpoint):
    query = endpoint(TEAMS_CSV)
    for parameter in ["_sort", "_sort_desc"]:
        response = query(f"?{parameter}=missing")
        assert response.status_code == 400, parameter
        assert response.get_json()["ok"] is False


# Phrase: "... unknown columns return `HTTP 400`." - column names are case-sensitive.
def test_sort_column_is_case_sensitive(endpoint):
    assert endpoint(TEAMS_CSV)("?_sort=NAME").status_code == 400


# Phrase: "... unknown columns return `HTTP 400`." - `rowid` is not a column (T21).
def test_sorting_by_rowid_is_400(endpoint):
    assert endpoint(TEAMS_CSV)("?_sort=rowid&_shape=objects").status_code == 400


# Phrase: "unknown columns return `HTTP 400`" - the losing parameter is checked too
# (T18).
def test_unknown_column_in_the_losing_sort_parameter_is_400(endpoint):
    assert endpoint(TEAMS_CSV)("?_sort=missing&_sort_desc=name").status_code == 400


# Phrase: "`_sort=<column>` sorts ascending" - mixed numbers and text order with
# numbers first (T17).
def test_mixed_typed_column_sorts_numbers_before_text(dataset):
    payload = dataset(MIXED_CSV, dataset_query="?_sort=value")
    assert names(payload) == ["e", "b", "a", "d", "c"]


# Phrase: "`_sort_desc=<column>` sorts descending" - the mirror image of ascending.
def test_mixed_typed_column_reverses_under_sort_desc(dataset):
    payload = dataset(MIXED_CSV, dataset_query="?_sort_desc=value")
    assert names(payload) == ["c", "d", "a", "b", "e"]
