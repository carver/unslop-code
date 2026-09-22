"""Tests for ingesting .xls and .xlsx workbooks through /convert and /upload."""

import io
import zipfile

import pytest

from workbooks import xls, xlsx

PEOPLE = [["name", "age", "city"], ["ada", 36, "london"], ["alan", 41, "wilmslow"]]

BUILDERS = pytest.mark.parametrize(
    ("build", "name"), [(xlsx, "a.xlsx"), (xls, "a.xls")], ids=["xlsx", "xls"]
)


@BUILDERS
def test_upload_reads_a_workbook(client, upload, build, name):
    response = upload(build(PEOPLE), name=name)

    dataset = client.get(response.json["endpoint"]).json
    assert dataset["columns"] == ["name", "age", "city"]
    assert dataset["rows"] == [["ada", 36, "london"], ["alan", 41, "wilmslow"]]


@BUILDERS
def test_convert_reads_a_workbook(client, serve, build, name):
    source = serve(name, build(PEOPLE))

    endpoint = client.get("/convert", query_string={"source": source}).json["endpoint"]

    assert client.get(endpoint).json["columns"] == ["name", "age", "city"]


@BUILDERS
def test_only_the_first_worksheet_is_ingested(client, upload, build, name):
    second = [["country", "code"], ["france", "fr"]]

    response = upload(build(PEOPLE, second), name=name)

    dataset = client.get(response.json["endpoint"]).json
    assert dataset["columns"] == ["name", "age", "city"]
    assert dataset["total"] == 2


@BUILDERS
def test_a_header_without_a_data_row_is_rejected(upload, build, name):
    assert upload(build([["name", "age"]]), name=name).status_code == 400


@BUILDERS
def test_an_empty_first_worksheet_is_rejected(upload, build, name):
    assert upload(build([], PEOPLE), name=name).status_code == 400


@BUILDERS
def test_charset_is_ignored_for_workbooks(client, build, name):
    response = client.post(
        "/upload",
        data={"file": (io.BytesIO(build(PEOPLE)), name)},
        content_type="multipart/form-data",
        query_string={"charset": "ascii"},
    )

    assert response.status_code == 200


@BUILDERS
def test_ragged_rows_are_squared_off_to_the_header(client, upload, build, name):
    grid = [["name", "age", "city"], ["ada", 36], ["alan", 41, "wilmslow", "extra"]]

    response = upload(build(grid), name=name)

    assert client.get(response.json["endpoint"]).json["rows"] == [
        ["ada", 36, ""],
        ["alan", 41, "wilmslow"],
    ]


def test_workbook_rows_export_as_csv(client, upload):
    endpoint = upload(xlsx(PEOPLE), name="a.xlsx").json["endpoint"]

    response = client.get(f"{endpoint}/export")

    assert response.headers["Content-Type"] == "text/csv"
    assert response.data.decode("utf-8").splitlines()[0] == "name,age,city"


def test_a_zip_that_is_not_a_workbook_is_rejected(upload):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as contents:
        contents.writestr("readme.txt", "hello")

    assert upload(archive.getvalue(), name="a.zip").status_code == 400


def test_a_truncated_workbook_is_rejected(upload):
    assert upload(xlsx(PEOPLE)[:200], name="a.xlsx").status_code == 400
    assert upload(xls(PEOPLE)[:200], name="a.xls").status_code == 400
