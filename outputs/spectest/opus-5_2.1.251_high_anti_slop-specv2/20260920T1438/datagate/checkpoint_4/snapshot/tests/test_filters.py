"""Column filtering of ``GET /datasets/<id>``."""

import pytest

from gateway import results

TABLE = b"name,score,start\nada,36,08:30\nlin,7,9:15\nbo,22,10:00\nadam,7,11:45\n"


def names(response) -> list:
    """The first cell of every returned row."""
    return [row[0] for row in response.get_json()["rows"]]


def test_exact_matches_whole_text(read):
    assert names(read(TABLE, name__exact="ada")) == ["ada"]


def test_exact_is_case_sensitive(read):
    assert names(read(TABLE, name__exact="Ada")) == []


def test_exact_matches_the_text_of_a_number(read):
    assert names(read(TABLE, score__exact="7")) == ["lin", "adam"]


def test_contains_matches_substrings(read):
    assert names(read(TABLE, name__contains="ada")) == ["ada", "adam"]


def test_contains_is_case_sensitive(read):
    assert names(read(TABLE, name__contains="AD")) == []


def test_contains_reaches_into_non_text_cells(read):
    assert names(read(TABLE, start__contains=":3")) == ["ada"]


def test_less_compares_numerically(read):
    assert names(read(TABLE, score__less="22")) == ["lin", "adam"]


def test_greater_compares_numerically(read):
    assert names(read(TABLE, score__greater="7")) == ["ada", "bo"]


@pytest.mark.parametrize("comparator", ["less", "greater"])
def test_numeric_comparators_are_strict(read, comparator):
    assert "bo" not in names(read(TABLE, **{f"score__{comparator}": "22"}))


def test_numeric_comparators_accept_decimal_values(read):
    assert names(read(TABLE, score__less="7.5")) == ["lin", "adam"]


@pytest.mark.parametrize("comparator", ["less", "greater"])
def test_non_numeric_cells_never_match_numeric_comparators(read, comparator):
    """``start`` holds clock times, which are text and so compare to nothing."""
    assert names(read(TABLE, **{f"start__{comparator}": "9"})) == []


def test_filters_are_combined_with_and(read):
    assert names(read(TABLE, name__contains="a", score__less="10")) == ["adam"]


def test_filtering_runs_before_sorting(read):
    response = read(TABLE, score__greater="7", _sort_desc="score")
    assert names(response) == ["ada", "bo"]


def test_total_counts_filtered_rows_before_pagination(read):
    body = read(TABLE, score__less="30", _size=1).get_json()
    assert body["total"] == 3
    assert len(body["rows"]) == 1


def test_pagination_cuts_into_the_filtered_rows(read):
    assert names(read(TABLE, score__less="30", _offset=1, _size=1)) == ["bo"]


def test_rowid_still_points_at_the_source_row(read):
    body = read(TABLE, name__exact="bo", _shape="objects").get_json()
    assert body["rows"] == [{"rowid": 4, "name": "bo", "score": 22, "start": "10:00"}]


def test_parameter_without_a_comparator_is_not_a_filter(read):
    assert names(read(TABLE, name="ada")) == ["ada", "lin", "bo", "adam"]


def test_parameter_starting_with_underscore_is_not_a_filter(read):
    """A leading ``_`` marks a control parameter, even shaped like a filter."""
    assert names(read(TABLE, __exact="ada")) == ["ada", "lin", "bo", "adam"]


@pytest.mark.parametrize(
    "key", ["name__equals", "name__EXACT", "name__", "score__lessthan"]
)
def test_unknown_comparator_is_rejected(read, key):
    response = read(TABLE, **{key: "1"})
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


@pytest.mark.parametrize("column", ["missing", "Name", "name "])
def test_unknown_filter_column_is_rejected(read, column):
    response = read(TABLE, **{f"{column}__exact": "ada"})
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


@pytest.mark.parametrize("comparator", ["less", "greater"])
@pytest.mark.parametrize("value", ["abc", "", "08:30"])
def test_non_numeric_filter_value_is_rejected(read, comparator, value):
    response = read(TABLE, **{f"score__{comparator}": value})
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


@pytest.mark.parametrize("comparator", ["exact", "contains"])
def test_text_comparators_accept_any_value(read, comparator):
    assert read(TABLE, **{f"name__{comparator}": ""}).status_code == 200


def test_repeated_filter_is_rejected(client, convert):
    endpoint = convert(TABLE).get_json()["endpoint"]
    response = client.get(endpoint, query_string={"name__exact": ["ada", "bo"]})
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


def test_column_named_with_the_separator_stays_addressable(read):
    payload = b"user__id,city\n7,oslo\n8,bergen\n"
    assert names(read(payload, user__id__exact="8")) == [8]


def test_timed_out_query_is_rejected(read, monkeypatch):
    monkeypatch.setattr(results, "QUERY_TIMEOUT_SECONDS", -1.0)
    response = read(TABLE, name__contains="a")
    assert response.status_code == 400
    assert response.get_json()["ok"] is False
