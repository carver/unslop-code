"""Spec section: Export, Upload, and Multi-Format Support - `GET /datasets/<id>/export`."""

from tests.conftest import SIMPLE_CSV, TEAMS_CSV, exported_rows, numbered_csv


# Phrase: "`GET /datasets/<id>/export` returns CSV bytes"
def test_export_returns_the_table_as_csv(client, convert):
    endpoint = convert(SIMPLE_CSV).get_json()["endpoint"]
    response = client.get(f"{endpoint}/export")
    assert response.status_code == 200
    assert exported_rows(response) == [["name", "age"], ["ada", "36"], ["grace", "45"]]


# Phrase: "returns CSV bytes with: `Content-Type: text/csv`"
def test_export_content_type_is_text_csv(client, convert):
    endpoint = convert(SIMPLE_CSV).get_json()["endpoint"]
    response = client.get(f"{endpoint}/export")
    assert response.headers["Content-Type"].startswith("text/csv")


# Phrase: "`Content-Disposition: attachment; filename="<dataset-id>.csv"`"
def test_export_content_disposition_names_the_dataset_id(client, convert):
    endpoint = convert(SIMPLE_CSV).get_json()["endpoint"]
    dataset_id = endpoint.removeprefix("/datasets/")
    response = client.get(f"{endpoint}/export")
    assert (
        response.headers["Content-Disposition"]
        == f'attachment; filename="{dataset_id}.csv"'
    )


# Phrase: "The CSV uses source column order" (T39: the header row is the first line).
def test_export_header_row_follows_source_column_order(client, convert):
    endpoint = convert("zeta,alpha,mid\n1,2,3\n").get_json()["endpoint"]
    assert exported_rows(client.get(f"{endpoint}/export"))[0] == ["zeta", "alpha", "mid"]


# Phrase: "applies the same filters ... as `/datasets/<id>`"
def test_export_applies_filters(client, convert):
    endpoint = convert(TEAMS_CSV).get_json()["endpoint"]
    rows = exported_rows(client.get(f"{endpoint}/export?team__exact=blue"))
    assert rows == [["name", "team", "age"], ["ada", "blue", "36"], ["alan", "blue", "41"]]


# Phrase: "applies the same ... sort ... as `/datasets/<id>`"
def test_export_applies_sort(client, convert):
    endpoint = convert(TEAMS_CSV).get_json()["endpoint"]
    rows = exported_rows(client.get(f"{endpoint}/export?_sort=age"))
    assert [row[0] for row in rows[1:]] == ["edsger", "ada", "alan", "grace"]


# Phrase: "applies the same ... sort ... as `/datasets/<id>`" - descending.
def test_export_applies_descending_sort(client, convert):
    endpoint = convert(TEAMS_CSV).get_json()["endpoint"]
    rows = exported_rows(client.get(f"{endpoint}/export?_sort_desc=age"))
    assert [row[0] for row in rows[1:]] == ["grace", "alan", "ada", "edsger"]


# Phrase: "applies the same ... pagination as `/datasets/<id>`"
def test_export_applies_size_and_offset(client, convert):
    endpoint = convert(numbered_csv(10)).get_json()["endpoint"]
    rows = exported_rows(client.get(f"{endpoint}/export?_size=3&_offset=4"))
    assert rows == [["n", "tag"], ["4", "row4"], ["5", "row5"], ["6", "row6"]]


# Phrase: "applies the same ... pagination" - the 100-row default page applies (T37).
def test_export_paginates_by_default(client, convert):
    endpoint = convert(numbered_csv(130)).get_json()["endpoint"]
    assert len(exported_rows(client.get(f"{endpoint}/export"))) == 101


# Phrase: "`_shape` ... does not affect CSV output."
def test_shape_does_not_affect_csv_output(client, convert):
    endpoint = convert(SIMPLE_CSV).get_json()["endpoint"]
    plain = client.get(f"{endpoint}/export").get_data()
    assert client.get(f"{endpoint}/export?_shape=objects").get_data() == plain
    assert client.get(f"{endpoint}/export?_shape=lists").get_data() == plain


# Phrase: "`_rowid` ... does not affect CSV output."
def test_rowid_does_not_affect_csv_output(client, convert):
    endpoint = convert(SIMPLE_CSV).get_json()["endpoint"]
    plain = client.get(f"{endpoint}/export").get_data()
    assert client.get(f"{endpoint}/export?_shape=objects&_rowid=hide").get_data() == plain


# Phrase: "`_total` do not affect CSV output."
def test_total_does_not_affect_csv_output(client, convert):
    endpoint = convert(SIMPLE_CSV).get_json()["endpoint"]
    plain = client.get(f"{endpoint}/export").get_data()
    assert client.get(f"{endpoint}/export?_total=hide").get_data() == plain


# Phrase: "the same filters, sort, and pagination" - their errors carry over too.
def test_export_rejects_invalid_controls_and_filters(client, convert):
    endpoint = convert(SIMPLE_CSV).get_json()["endpoint"]
    for query in ["?_size=0", "?_sort=nope", "?_offset=-1", "?name__nope=ada", "?age__less=x"]:
        response = client.get(f"{endpoint}/export{query}")
        assert response.status_code == 400, query
        assert response.get_json()["ok"] is False, query


# Phrase: "all errors use the standard JSON envelope" - an unknown dataset id.
def test_export_of_unknown_dataset_is_404_envelope(client):
    response = client.get("/datasets/deadbeefdeadbeef/export")
    assert response.status_code == 404
    assert response.get_json()["ok"] is False
    assert isinstance(response.get_json()["error"], str)


# Phrase: "semantically-correct CSV is required" - separators inside cells survive.
def test_export_quotes_cells_containing_separators(client, convert):
    endpoint = convert('a,b\n"x,1","he said ""hi"""\n').get_json()["endpoint"]
    assert exported_rows(client.get(f"{endpoint}/export"))[1] == ["x,1", 'he said "hi"']
