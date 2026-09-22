"""Spec sections: Response shape and Visibility toggles."""

CSV = "name,score\ncarol,7\nalice,3\nbob,7\n"


# Phrase: "`_shape=lists` (default): `rows` is arrays."
def test_default_shape_is_lists(converted):
    body = converted(CSV).get_json()

    assert body["rows"] == [["carol", 7], ["alice", 3], ["bob", 7]]


# Phrase: "`_shape=lists` (default): `rows` is arrays."
def test_explicit_lists_shape(converted):
    body = converted(CSV, query="?_shape=lists").get_json()

    assert body["rows"] == [["carol", 7], ["alice", 3], ["bob", 7]]


# Phrase: "`_shape=lists` ... `rows` is arrays." -- context: no rowid in list rows.
def test_lists_shape_has_no_rowid(converted):
    body = converted(CSV, query="?_shape=lists").get_json()

    assert all(len(row) == 2 for row in body["rows"])


# Phrase: "`_shape=objects`: `rows` is objects and includes `rowid`"
def test_objects_shape_rows_are_objects_with_rowid(converted):
    body = converted(CSV, query="?_shape=objects").get_json()

    assert body["rows"][0] == {"rowid": 1, "name": "carol", "score": 7}


# Phrase: "`rowid` (1-based source-file row number)" -- context: numbering (AMBIGUITIES T13).
def test_rowid_numbers_data_rows_from_one(converted):
    body = converted(CSV, query="?_shape=objects").get_json()

    assert [row["rowid"] for row in body["rows"]] == [1, 2, 3]


# Phrase: "`rowid` (1-based source-file row number)" -- context: it tracks the source row,
# not the position in the sorted page.
def test_rowid_follows_the_source_row_through_sorting(converted):
    body = converted(CSV, query="?_shape=objects&_sort=name").get_json()

    assert [(row["name"], row["rowid"]) for row in body["rows"]] == [
        ("alice", 2),
        ("bob", 3),
        ("carol", 1),
    ]


# Phrase: "`rowid` (1-based source-file row number)" -- context: it survives an offset.
def test_rowid_survives_pagination(converted):
    body = converted(CSV, query="?_shape=objects&_offset=2").get_json()

    assert [row["rowid"] for row in body["rows"]] == [3]


# Phrase: "`rowid` is not in `columns`."
def test_rowid_is_not_a_column(converted):
    body = converted(CSV, query="?_shape=objects").get_json()

    assert body["columns"] == ["name", "score"]


# Phrase: "`_rowid=hide` removes `rowid`."
def test_rowid_hide_removes_rowid(converted):
    body = converted(CSV, query="?_shape=objects&_rowid=hide").get_json()

    assert body["rows"][0] == {"name": "carol", "score": 7}


# Phrase: "`_rowid=hide` removes `rowid`." -- context: harmless in lists shape (AMBIGUITIES T19).
def test_rowid_hide_is_accepted_in_lists_shape(converted):
    response = converted(CSV, query="?_rowid=hide")

    assert response.status_code == 200
    assert response.get_json()["rows"][0] == ["carol", 7]


# Phrase: "`_total=hide` removes `total`."
def test_total_hide_removes_total(converted):
    body = converted(CSV, query="?_total=hide").get_json()

    assert "total" not in body
    assert body["ok"] is True


# Phrase: "`_total=hide` removes `total`." -- context: the rest of the envelope stays.
def test_total_hide_keeps_other_keys(converted):
    body = converted(CSV, query="?_total=hide&_shape=objects").get_json()

    assert set(body) == {"ok", "columns", "rows", "query_ms"}


# Phrase: "`_shape=objects`" -- context: pagination and shape combine.
def test_objects_shape_respects_pagination(converted):
    body = converted(CSV, query="?_shape=objects&_size=1&_offset=1").get_json()

    assert body["rows"] == [{"rowid": 2, "name": "alice", "score": 3}]
    assert body["total"] == 3


# Phrase: "`_shape=objects`: `rows` is objects" -- context: a column named `rowid`
# does not displace the row number (AMBIGUITIES T22).
def test_rowid_column_does_not_displace_the_row_number(converted):
    body = converted("rowid,name\n9,ada\n", query="?_shape=objects").get_json()

    assert body["rows"] == [{"rowid": 1, "name": "ada"}]
