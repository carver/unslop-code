"""The `Sorting` section and the key/null rules of `Casting & Validation`."""
from conftest import merge, run, write, write_schema


# --- Spec: "Sort by composite key specified via `--key` (one or more columns)"
def test_single_key_ascending(tmp_path):
    files = {"a.csv": "id\n3\n1\n2\n"}
    r = merge(tmp_path, files, "--key", "id")
    assert r.ok, r
    assert [x[0] for x in r.rows()[1:]] == ["1", "2", "3"]


# --- Spec: "Sort by composite key ... (one or more columns)" ----------------
def test_composite_key(tmp_path):
    files = {
        "a.csv": "g,n\nb,1\na,2\nb,0\na,1\n",
    }
    r = merge(tmp_path, files, "--key", "g,n")
    assert r.ok, r
    assert r.rows()[1:] == [["a", "1"], ["a", "2"], ["b", "0"], ["b", "1"]]


# --- Spec: "Default order is ascending" -------------------------------------
def test_default_is_ascending(tmp_path):
    files = {"a.csv": "s\nb\nc\na\n"}
    r = merge(tmp_path, files, "--key", "s")
    assert r.ok, r
    assert [x[0] for x in r.rows()[1:]] == ["a", "b", "c"]


# --- Spec: "`--desc` applies to all keys" -----------------------------------
def test_desc_applies_to_every_key(tmp_path):
    files = {"a.csv": "g,n\na,1\na,2\nb,1\nb,2\n"}
    r = merge(tmp_path, files, "--key", "g,n", "--desc")
    assert r.ok, r
    assert r.rows()[1:] == [["b", "2"], ["b", "1"], ["a", "2"], ["a", "1"]]


# --- Spec: "Sort must be stable with respect to input appearance for equal
#            keys" - ties keep file order then row order -------------------
def test_stability_ascending(tmp_path):
    files = {
        "a.csv": "k,tag\n1,a1\n1,a2\n",
        "b.csv": "k,tag\n1,b1\n1,b2\n",
    }
    r = merge(tmp_path, files, "--key", "k")
    assert r.ok, r
    assert [x[1] for x in r.rows()[1:]] == ["a1", "a2", "b1", "b2"]


# --- Spec: "Sort must be stable ..." also holds under `--desc`
#           (see AMBIGUITIES T14) -------------------------------------------
def test_stability_descending(tmp_path):
    files = {
        "a.csv": "k,tag\n1,a1\n1,a2\n",
        "b.csv": "k,tag\n1,b1\n1,b2\n",
    }
    r = merge(tmp_path, files, "--key", "k", "--desc")
    assert r.ok, r
    assert [x[1] for x in r.rows()[1:]] == ["a1", "a2", "b1", "b2"]


# --- Spec: "Sort must be stable ..." - mixed keys, ties within each group ----
def test_stability_within_groups(tmp_path):
    files = {
        "a.csv": "k,tag\n2,a1\n1,a2\n2,a3\n",
        "b.csv": "k,tag\n1,b1\n2,b2\n",
    }
    r = merge(tmp_path, files, "--key", "k")
    assert r.ok, r
    assert [x[1] for x in r.rows()[1:]] == ["a2", "b1", "a1", "a3", "b2"]


# --- Spec: sorting uses the resolved type, so int keys compare numerically ---
def test_int_key_sorts_numerically(tmp_path):
    files = {"a.csv": "id\n10\n9\n100\n"}
    r = merge(tmp_path, files, "--key", "id")
    assert r.ok, r
    assert [x[0] for x in r.rows()[1:]] == ["9", "10", "100"]


# --- Spec: string keys compare lexicographically -----------------------------
def test_string_key_sorts_lexicographically(tmp_path):
    files = {"a.csv": "id\n10\n9\nx\n"}
    r = merge(tmp_path, files, "--key", "id")
    assert r.ok, r
    # mixed values force `string`, so codepoint order applies
    assert [x[0] for x in r.rows()[1:]] == ["10", "9", "x"]


# --- Spec: float keys compare numerically -----------------------------------
def test_float_key_sorts_numerically(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("v", "float")])
    files = {"a.csv": "v\n10.5\n2.25\n-3\n"}
    r = merge(tmp_path, files, "--key", "v", "--schema", str(schema))
    assert r.ok, r
    assert [x[0] for x in r.rows()[1:]] == ["-3.0", "2.25", "10.5"]


# --- Spec: timestamp keys compare as instants (zone-aware) ------------------
def test_timestamp_key_sorts_chronologically(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("ts", "timestamp")])
    files = {
        "a.csv": "ts\n2024-07-01T12:00:00+02:00\n2024-07-01T09:30:00Z\n"
    }
    r = merge(tmp_path, files, "--key", "ts", "--schema", str(schema))
    assert r.ok, r
    assert [x[0] for x in r.rows()[1:]] == [
        "2024-07-01T09:30:00Z",
        "2024-07-01T10:00:00Z",
    ]


# --- Spec: "Nulls always compare less than non-null values ... (first in
#            ascending ...)" ------------------------------------------------
def test_nulls_first_ascending(tmp_path):
    files = {"a.csv": "id,k\n1,5\n2,\n3,1\n"}
    schema = write_schema(tmp_path, "s.json", [("id", "int"), ("k", "int")])
    r = merge(tmp_path, files, "--key", "k", "--schema", str(schema))
    assert r.ok, r
    assert [x[0] for x in r.rows()[1:]] == ["2", "3", "1"]


# --- Spec: "Nulls always compare less ... (... last in descending)" ---------
def test_nulls_last_descending(tmp_path):
    files = {"a.csv": "id,k\n1,5\n2,\n3,1\n"}
    schema = write_schema(tmp_path, "s.json", [("id", "int"), ("k", "int")])
    r = merge(tmp_path, files, "--key", "k", "--schema", str(schema), "--desc")
    assert r.ok, r
    assert [x[0] for x in r.rows()[1:]] == ["1", "3", "2"]


# --- Spec: nulls from a *missing column* also sort first --------------------
def test_missing_column_nulls_sort_first(tmp_path):
    files = {
        "a.csv": "id\n1\n",
        "b.csv": "id,k\n2,7\n",
    }
    r = merge(tmp_path, files, "--key", "k")
    assert r.ok, r
    assert [x[0] for x in r.rows()[1:]] == ["1", "2"]


# --- Spec: "If a key column is not present in resolved schema, that is an
#            error" (inferred schema) ---------------------------------------
def test_unknown_key_column_is_error_inferred(tmp_path):
    files = {"a.csv": "id\n1\n"}
    r = merge(tmp_path, files, "--key", "nope")
    assert not r.ok
    assert "nope" in r.stderr


# --- Spec: "If a key column is not present in resolved schema, that is an
#            error" (explicit schema: column exists in input but not schema) -
def test_unknown_key_column_is_error_with_schema(tmp_path):
    schema = write_schema(tmp_path, "s.json", [("id", "int")])
    files = {"a.csv": "id,other\n1,2\n"}
    r = merge(tmp_path, files, "--key", "other", "--schema", str(schema))
    assert not r.ok
    assert "other" in r.stderr


# --- Spec: "Tool must handle inputs exceeding `--memory-limit-mb` constraint"
def test_sorts_correctly_when_exceeding_memory_limit(tmp_path):
    n = 4000
    rows_a = "".join(f"{(i * 7919) % n},a{i}\n" for i in range(n))
    rows_b = "".join(f"{(i * 104729) % n},b{i}\n" for i in range(n))
    files = {
        "a.csv": "id,tag\n" + rows_a,
        "b.csv": "id,tag\n" + rows_b,
    }
    r = merge(tmp_path, files, "--key", "id", "--memory-limit-mb", "1")
    assert r.ok, r.stderr
    out = r.rows()
    assert len(out) == 2 * n + 1
    ids = [int(x[0]) for x in out[1:]]
    assert ids == sorted(ids)
