"""Tests for the /datasets column filters and how they combine with the controls."""

import pytest

from datagate import query

CSV = (
    b"name,age,city\n"
    b"ada,36,london\n"
    b"Grace,45,new york\n"
    b"alan,41,wilmslow\n"
    b"edsger,36,austin\n"
    b"marvin,n/a,new haven\n"
)


@pytest.fixture
def endpoint(client, serve):
    """Convert the five-row fixture CSV and return its dataset endpoint."""
    source = serve("people.csv", CSV)
    return client.get("/convert", query_string={"source": source}).json["endpoint"]


def names(response):
    return [row[0] for row in response.json["rows"]]


def test_exact_matches_whole_cell(client, endpoint):
    assert names(client.get(f"{endpoint}?city__exact=new york")) == ["Grace"]


def test_exact_does_not_match_a_substring(client, endpoint):
    assert client.get(f"{endpoint}?city__exact=new").json["rows"] == []


def test_exact_is_case_sensitive(client, endpoint):
    assert client.get(f"{endpoint}?name__exact=grace").json["rows"] == []
    assert names(client.get(f"{endpoint}?name__exact=Grace")) == ["Grace"]


def test_exact_matches_numeric_cells_by_text(client, endpoint):
    assert names(client.get(f"{endpoint}?age__exact=36")) == ["ada", "edsger"]


def test_contains_matches_a_substring(client, endpoint):
    assert names(client.get(f"{endpoint}?city__contains=new")) == ["Grace", "marvin"]


def test_contains_is_case_sensitive(client, endpoint):
    assert client.get(f"{endpoint}?city__contains=NEW").json["rows"] == []


def test_less_is_strict(client, endpoint):
    assert names(client.get(f"{endpoint}?age__less=41")) == ["ada", "edsger"]


def test_greater_is_strict(client, endpoint):
    assert names(client.get(f"{endpoint}?age__greater=41")) == ["Grace"]


def test_numeric_comparators_accept_decimal_values(client, endpoint):
    assert names(client.get(f"{endpoint}?age__greater=40.5")) == ["Grace", "alan"]


def test_numeric_comparators_skip_non_numeric_cells(client, endpoint):
    assert "marvin" not in names(client.get(f"{endpoint}?age__greater=0"))
    assert "marvin" not in names(client.get(f"{endpoint}?age__less=1000"))


def test_filters_are_combined_with_and(client, endpoint):
    response = client.get(f"{endpoint}?age__greater=36&city__contains=w")
    assert names(response) == ["Grace", "alan"]


def test_two_filters_on_one_column_are_combined(client, endpoint):
    response = client.get(f"{endpoint}?age__greater=36&age__less=45")
    assert names(response) == ["alan"]


def test_filter_matching_nothing_returns_no_rows(client, endpoint):
    response = client.get(f"{endpoint}?name__exact=turing")

    assert response.json["rows"] == []
    assert response.json["total"] == 0


def test_total_counts_filtered_rows_before_pagination(client, endpoint):
    response = client.get(f"{endpoint}?age__exact=36&_size=1")

    assert response.json["total"] == 2
    assert len(response.json["rows"]) == 1


def test_filtering_precedes_sorting(client, endpoint):
    response = client.get(f"{endpoint}?age__greater=36&_sort=name")

    assert names(response) == ["Grace", "alan"]


def test_pagination_runs_on_filtered_and_sorted_rows(client, endpoint):
    response = client.get(f"{endpoint}?age__less=45&_sort=name&_size=2&_offset=1")

    assert names(response) == ["alan", "edsger"]


def test_rowid_still_reports_the_source_position(client, endpoint):
    response = client.get(f"{endpoint}?age__exact=36&_shape=objects")

    assert [row["rowid"] for row in response.json["rows"]] == [1, 4]


def test_parameters_without_a_comparator_are_ignored(client, endpoint):
    response = client.get(f"{endpoint}?name=ada&height=180")

    assert response.json["total"] == 5


def test_unknown_control_parameters_are_not_filters(client, endpoint):
    assert client.get(f"{endpoint}?_unknown=1").json["total"] == 5
    assert client.get(f"{endpoint}?__exact=ada").json["total"] == 5


@pytest.mark.parametrize(
    "filters",
    [
        "name__equals=ada",
        "name__=ada",
        "name__EXACT=ada",
        "name__contain=ada",
        "height__exact=180",
        "name__exact__contains=ada",
        "age__less=old",
        "age__less=",
        "age__greater=41a",
        "age__greater=n/a",
        "name__exact=ada&name__exact=ada",
        "age__less=40&age__less=40",
    ],
)
def test_invalid_filters_are_rejected(client, endpoint, filters):
    response = client.get(f"{endpoint}?{filters}")

    assert response.status_code == 400
    assert response.json["ok"] is False
    assert isinstance(response.json["error"], str)


def test_query_timeout_is_reported(client, endpoint, monkeypatch):
    monkeypatch.setattr(query, "QUERY_TIMEOUT_SECONDS", -1.0)

    response = client.get(f"{endpoint}?age__greater=0")

    assert response.status_code == 400
    assert response.json["ok"] is False
