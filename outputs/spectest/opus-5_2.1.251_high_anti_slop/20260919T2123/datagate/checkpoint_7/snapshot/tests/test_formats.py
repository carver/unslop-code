"""Tests for ingesting spreadsheets alongside CSV text."""

import pytest

from helpers import convert, load


@pytest.mark.parametrize("fixture", ["staff.xls", "staff.xlsx"])
def test_workbook_columns_and_rows_keep_their_source_order(client, base_url, fixture):
    payload = load(client, base_url, fixture)
    assert payload["columns"] == ["name", "role", "age", "rating"]
    assert payload["rows"] == [
        ["Ada", "engineer", 36, 9.5],
        ["Grace", "engineer", 45, 8.25],
        ["Alan", "analyst", 41, 9.5],
        ["ada", "analyst", 29, "n/a"],
    ]


@pytest.mark.parametrize("fixture", ["staff.xls", "staff.xlsx"])
def test_only_the_first_worksheet_is_ingested(client, base_url, fixture):
    assert "note" not in load(client, base_url, fixture)["columns"]


@pytest.mark.parametrize("fixture", ["staff.xls", "staff.xlsx"])
def test_workbook_rows_can_be_filtered_and_sorted(client, base_url, fixture):
    endpoint = convert(client, base_url, fixture).get_json()["endpoint"]
    payload = client.get(
        endpoint, query_string={"role__exact": "engineer", "_sort_desc": "age"}
    ).get_json()
    assert [row[0] for row in payload["rows"]] == ["Grace", "Ada"]


def test_a_workbook_and_its_csv_twin_agree(client, base_url):
    workbook = load(client, base_url, "staff.xlsx")
    assert workbook["rows"] == load(client, base_url, "staff.csv")["rows"]


@pytest.mark.parametrize("fixture", ["header_only.xls", "header_only.xlsx"])
def test_a_workbook_without_data_rows_is_rejected(client, base_url, fixture):
    assert convert(client, base_url, fixture).status_code == 400


def test_an_archive_that_is_not_a_workbook_is_rejected(client, base_url):
    assert convert(client, base_url, "archive.xlsx").status_code == 400


def test_charset_is_ignored_for_workbooks(client, base_url):
    """The bytes of a workbook are not text, so a charset has nothing to apply to."""
    payload = load(client, base_url, "accents.xlsx", charset="cp1252")
    assert payload["rows"] == [["José", "Málaga"]]


def test_a_workbook_keeps_its_source_url_id(client, base_url):
    first = convert(client, base_url, "staff.xlsx").get_json()["endpoint"]
    second = convert(client, base_url, "staff.xlsx").get_json()["endpoint"]
    assert first == second
