"""The `Casting & Validation` section."""
from conftest import merge, run, write, write_schema


def one_col(tmp_path, typ, values, *args, key="v"):
    schema = write_schema(tmp_path, f"s_{typ}.json", [("v", typ)])
    body = "v\n" + "".join(f"{v}\n" for v in values)
    return merge(tmp_path, {"in.csv": body}, "--key", key, "--schema", str(schema), *args)


# --- Spec: "`int`, `float`, `string`: standard parsing" ---------------------
def test_int_parsing(tmp_path):
    r = one_col(tmp_path, "int", ["1", "-2", "+3", "007"])
    assert r.ok, r
    assert [x[0] for x in r.rows()[1:]] == ["-2", "1", "3", "7"]


def test_float_parsing(tmp_path):
    r = one_col(tmp_path, "float", ["1", "-2.5", "3.0", "1e2", "0.75"])
    assert r.ok, r
    assert [x[0] for x in r.rows()[1:]] == ["-2.5", "0.75", "1.0", "3.0", "100.0"]


def test_string_parsing_is_passthrough(tmp_path):
    r = one_col(tmp_path, "string", ["b", "a", "007"])
    assert r.ok, r
    assert [x[0] for x in r.rows()[1:]] == ["007", "a", "b"]


# --- Spec: "`bool` includes `1`/`0` along with standard values" ------------
def test_bool_accepts_one_and_zero(tmp_path):
    r = one_col(tmp_path, "bool", ["1", "0"])
    assert r.ok, r
    assert [x[0] for x in r.rows()[1:]] == ["false", "true"]


def test_bool_accepts_true_false(tmp_path):
    r = one_col(tmp_path, "bool", ["true", "false", "TRUE", "False"])
    assert r.ok, r
    assert [x[0] for x in r.rows()[1:]] == ["false", "false", "true", "true"]


# --- Spec: "`date`: ISO-8601 `YYYY-MM-DD`" --------------------------------
def test_date_parsing(tmp_path):
    r = one_col(tmp_path, "date", ["2024-07-01", "1999-12-31"])
    assert r.ok, r
    assert [x[0] for x in r.rows()[1:]] == ["1999-12-31", "2024-07-01"]


# --- Spec: "`date`: ISO-8601 `YYYY-MM-DD`" - other shapes fail the cast ----
def test_date_rejects_non_iso(tmp_path):
    r = one_col(tmp_path, "date", ["07/01/2024"])
    assert r.ok, r
    assert r.rows()[1] == [""]  # coerce-null default


# --- Spec: "`timestamp`: ISO-8601 format; normalize to UTC with `Z` suffix" -
def test_timestamp_normalizes_to_utc(tmp_path):
    r = one_col(
        tmp_path,
        "timestamp",
        [
            "2024-07-01T12:00:00Z",
            "2024-07-01T14:00:00+02:00",
            "2024-07-01T10:00:00-01:00",
        ],
    )
    assert r.ok, r
    assert [x[0] for x in r.rows()[1:]] == [
        "2024-07-01T11:00:00Z",
        "2024-07-01T12:00:00Z",
        "2024-07-01T12:00:00Z",
    ]


# --- Spec: "if source lacked zone, treat as UTC" --------------------------
def test_naive_timestamp_treated_as_utc(tmp_path):
    r = one_col(tmp_path, "timestamp", ["2024-07-01T12:00:00"])
    assert r.ok, r
    assert r.rows()[1] == ["2024-07-01T12:00:00Z"]


# --- Spec: "On cast failure, apply `--on-type-error`: `coerce-null`
#            (default): emit null literal for that cell" ------------------
def test_coerce_null_is_the_default(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("id", "int"), ("v", "int")])
    files = {"a.csv": "id,v\n1,oops\n"}
    r = merge(tmp_path, files, "--key", "id", "--schema", str(schema))
    assert r.ok, r
    assert r.rows()[1] == ["1", ""]


def test_coerce_null_explicit_uses_null_literal(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("id", "int"), ("v", "int")])
    files = {"a.csv": "id,v\n1,oops\n"}
    r = merge(
        tmp_path, files, "--key", "id", "--schema", str(schema),
        "--on-type-error", "coerce-null", "--csv-null-literal", "NULL",
    )
    assert r.ok, r
    assert r.rows()[1] == ["1", "NULL"]


# --- Spec: "`fail`: write error to stderr and exit non-zero" --------------
def test_fail_mode(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("id", "int"), ("v", "int")])
    files = {"a.csv": "id,v\n1,oops\n"}
    r = merge(
        tmp_path, files, "--key", "id", "--schema", str(schema),
        "--on-type-error", "fail",
    )
    assert not r.ok
    assert r.stderr.strip()


# --- Spec: "`fail`" does not trip on values that cast cleanly -------------
def test_fail_mode_passes_clean_input(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("id", "int"), ("v", "int")])
    files = {"a.csv": "id,v\n1,2\n"}
    r = merge(
        tmp_path, files, "--key", "id", "--schema", str(schema),
        "--on-type-error", "fail",
    )
    assert r.ok, r


# --- Spec: nulls are not cast failures, so `fail` tolerates them ----------
def test_fail_mode_tolerates_nulls(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("id", "int"), ("v", "int")])
    files = {"a.csv": "id,v\n1,\n"}
    r = merge(
        tmp_path, files, "--key", "id", "--schema", str(schema),
        "--on-type-error", "fail",
    )
    assert r.ok, r
    assert r.rows()[1] == ["1", ""]


# --- Spec: "`keep-string`: emit original text as string" ------------------
def test_keep_string_mode(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("id", "int"), ("v", "int")])
    files = {"a.csv": "id,v\n1,oops\n2,03\n"}
    r = merge(
        tmp_path, files, "--key", "id", "--schema", str(schema),
        "--on-type-error", "keep-string",
    )
    assert r.ok, r
    assert r.rows()[1:] == [["1", "oops"], ["2", "3"]]


# --- Spec: "Cast every input cell into target type" - failures in a *key*
#           column still produce a total order (see AMBIGUITIES T13) ------
def test_keep_string_key_column_orders_after_typed_values(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("id", "string"), ("v", "int")])
    files = {"a.csv": "id,v\na,5\nb,oops\nc,\n"}
    r = merge(
        tmp_path, files, "--key", "v", "--schema", str(schema),
        "--on-type-error", "keep-string",
    )
    assert r.ok, r
    assert [x[0] for x in r.rows()[1:]] == ["c", "a", "b"]


# --- Spec ambiguity T21: non-finite floats are not valid floats -----------
def test_non_finite_floats_are_cast_failures(tmp_path):
    r = one_col(tmp_path, "float", ["nan", "inf"])
    assert r.ok, r
    assert [x[0] for x in r.rows()[1:]] == ["", ""]


# --- Spec: an int column rejects decimal text ----------------------------
def test_int_rejects_decimal_text(tmp_path):
    r = one_col(tmp_path, "int", ["5.0"], "--on-type-error", "keep-string")
    assert r.ok, r
    assert r.rows()[1] == ["5.0"]


# --- Spec: "`bool` includes 1/0 along with standard values" - other words
#           are cast failures (see AMBIGUITIES T4) -----------------------
def test_bool_rejects_other_words(tmp_path):
    r = one_col(tmp_path, "bool", ["maybe"])
    assert r.ok, r
    assert r.rows()[1] == [""]


# --- Spec ambiguity T3: a date-only value cast into a timestamp column ---
def test_timestamp_accepts_date_only(tmp_path):
    r = one_col(tmp_path, "timestamp", ["2024-07-01"])
    assert r.ok, r
    assert r.rows()[1] == ["2024-07-01T00:00:00Z"]
