"""Spec section: Dataset Query `GET /datasets/<id>`."""

from conftest import SIMPLE_CSV


# Phrase: "Success (HTTP 200): {"ok": true, "columns": [...], "rows": [...], "query_ms": 3.2}"
def test_dataset_payload_shape(client, serve):
    endpoint = client.get("/convert", query_string={"source": serve(SIMPLE_CSV)}).get_json()["endpoint"]

    response = client.get(endpoint)

    assert response.status_code == 200
    body = response.get_json()
    assert set(body) == {"ok", "columns", "rows", "total", "query_ms"}
    assert body["ok"] is True


# Phrase: "The endpoint returns stored rows and columns, in source order."
def test_rows_and_columns_follow_source_order(dataset):
    body = dataset("b,a,c\n2,1,3\n5,4,6\n")

    assert body["columns"] == ["b", "a", "c"]
    assert body["rows"] == [[2, 1, 3], [5, 4, 6]]


# Phrase: "`rows` returns at most 100 items (or all rows if fewer)."
def test_row_limit_is_100(dataset):
    body = dataset("n\n" + "".join(f"{i}\n" for i in range(150)))

    assert len(body["rows"]) == 100
    assert body["rows"][0] == [0]
    assert body["rows"][-1] == [99]


# Phrase: "(or all rows if fewer)"
def test_short_datasets_return_every_row(dataset):
    body = dataset(SIMPLE_CSV)

    assert body["rows"] == [["ada", 36], ["grace", 45]]


# Phrase: "Default row limit is 100." (context: T11 — `_size` is now the documented override)
def test_page_size_is_overridden_with_size(dataset):
    body = dataset("n\n" + "".join(f"{i}\n" for i in range(150)), query="?_size=5")

    assert body["rows"] == [[0], [1], [2], [3], [4]]


# Phrase: "Default row limit is 100." (context: T24 — undocumented parameters are ignored)
def test_unknown_query_parameters_are_ignored(dataset):
    csv_body = "n\n" + "".join(f"{i}\n" for i in range(150))

    for query in ("?limit=5", "?sort=n", "?page=2"):
        assert len(dataset(csv_body, query=query)["rows"]) == 100


# Phrase: "Strings remain text."
def test_strings_remain_text(dataset):
    body = dataset("word,code\nada,A1\nhello world,3 of 4\n")

    assert body["rows"] == [["ada", "A1"], ["hello world", "3 of 4"]]


# Phrase: "Integers/decimals are JSON numbers."
def test_integers_and_decimals_become_numbers(dataset):
    body = dataset("i,d,neg,exp\n42,3.14,-7,1e3\n")

    assert body["rows"] == [[42, 3.14, -7, 1000.0]]
    assert isinstance(body["rows"][0][0], int)
    assert isinstance(body["rows"][0][1], float)


# Phrase: "Time-like values (for example `08:30`, `9:15`, `12:00`) remain text."
def test_time_like_values_remain_text(dataset):
    body = dataset("start,mid,end\n08:30,9:15,12:00\n")

    assert body["rows"] == [["08:30", "9:15", "12:00"]]


# Phrase: "Time-like values ... remain text." (context: dates and durations are not numbers either)
def test_other_non_numeric_shapes_remain_text(dataset):
    body = dataset("date,duration,percent\n2024-01-05,1:02:03,12.5%\n")

    assert body["rows"] == [["2024-01-05", "1:02:03", "12.5%"]]


# Phrase: "Integers/decimals are JSON numbers." (context: T3 — non-JSON floats stay text)
def test_nan_and_infinity_remain_text(dataset):
    body = dataset("a,b,c\nnan,inf,-Infinity\n")

    assert body["rows"] == [["nan", "inf", "-Infinity"]]


# Phrase: "Strings remain text." (context: T14 — empty cells)
def test_empty_cells_are_empty_strings(dataset):
    body = dataset("a,b\n,2\n")

    assert body["rows"] == [["", 2]]


# Phrase: "Integers/decimals are JSON numbers." (context: T12 — padded numeric cells)
def test_padded_numbers_are_numbers_and_padded_text_is_preserved(dataset):
    body = dataset('a,b\n" 42 "," x "\n')

    assert body["rows"] == [[42, " x "]]


# Phrase: "columns and each row follow source column order." (context: T5 — ragged rows)
def test_ragged_rows_are_aligned_to_the_header(dataset):
    body = dataset("a,b,c\n1,2\n4,5,6,7\n")

    assert body["rows"] == [[1, 2, ""], [4, 5, 6]]


# Phrase: "query_ms": 3.2 / "query_ms is present and non-negative."
def test_query_ms_is_a_non_negative_number(dataset):
    body = dataset(SIMPLE_CSV)

    assert isinstance(body["query_ms"], (int, float))
    assert body["query_ms"] >= 0


# Phrase: "If `<id>` is unknown, return HTTP 404."
def test_unknown_dataset_id_is_404(client):
    response = client.get("/datasets/0123456789abcdef")

    assert response.status_code == 404
    assert response.get_json()["ok"] is False


# Phrase: "If `<id>` is unknown, return HTTP 404." (context: T25 — identity is checked before controls)
def test_unknown_dataset_id_beats_invalid_controls(client):
    response = client.get("/datasets/0123456789abcdef?_size=0")

    assert response.status_code == 404
