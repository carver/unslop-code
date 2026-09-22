"""Spec section: Determinism Checklist — "Exact exit codes and stderr message
shape as specified". See AMBIGUITIES T26 for the inferred taxonomy."""

from conftest import (pa, run, run_ok, write, write_jsonl, write_parquet,
                      write_schema)


def stderr_shape(res):
    """Every diagnostic is a single `merge_files.py: error: ...` line."""
    err = res.stderr.strip()
    assert err != ""
    first = err.split("\n")[0]
    return first


# --- Spec: "otherwise error 2" (undeterminable input format) ---
# Context: New Input Types.
def test_exit_2_for_undeterminable_format(ws):
    a = write(ws / "a.dat", "id\n1\n")
    res = run("--output", "-", "--key", "id", a)
    assert res.returncode == 2
    assert "error" in stderr_shape(res)


# --- Spec: a successful run exits 0 and says nothing on stderr ---
# Context: Determinism Checklist.
def test_exit_0_and_silent_stderr_on_success(ws):
    a = write_jsonl(ws / "a.jsonl", [{"id": 1}])
    res = run("--output", "-", "--key", "id", a)
    assert res.returncode == 0
    assert res.stderr == ""


# --- Spec: "Keys must exist in resolved schema (error 3 otherwise)" ---
# Context: Sorting and Stability.
def test_exit_3_for_unknown_key(ws):
    a = write(ws / "a.csv", "id\n1\n")
    res = run("--output", "-", "--key", "missing", a)
    assert res.returncode == 3


# --- Spec: schema documents are a schema-level concern ---
# Context: Schema Resolution; a malformed --schema document (see T26).
def test_exit_3_for_invalid_schema_document(ws):
    a = write(ws / "a.csv", "id\n1\n")
    s = write(ws / "s.json", "{not json")
    res = run("--output", "-", "--key", "id", "--schema", s, a)
    assert res.returncode == 3


# --- Spec: schema types come from the fixed type vocabulary ---
# Context: Schema Resolution; an unknown declared type (see T26).
def test_exit_3_for_unknown_schema_type(ws):
    a = write(ws / "a.csv", "id\n1\n")
    s = write_schema(ws / "s.json", [("id", "decimal")])
    res = run("--output", "-", "--key", "id", "--schema", s, a)
    assert res.returncode == 3


# --- Spec: "`fail`: write error to stderr and exit non-zero" (checkpoint 1) ---
# Context: Casting; the remaining numbered class is 4 (see T26).
def test_exit_4_for_cast_failure_under_fail(ws):
    a = write(ws / "a.csv", "id,v\n1,oops\n")
    s = write_schema(ws / "s.json", [("id", "int"), ("v", "int")])
    res = run("--output", "-", "--key", "id", "--schema", s,
              "--on-type-error", "fail", a)
    assert res.returncode == 4
    assert "error" in stderr_shape(res)


# --- Spec: "Mismatch is error 5" ---
# Context: New Input Types, compression.
def test_exit_5_for_compression_mismatch(ws):
    a = write(ws / "a.csv", "id\n1\n")
    res = run("--output", "-", "--key", "id", "--compression", "gzip", a)
    assert res.returncode == 5


# --- Spec: "literal tabs inside field not allowed (error 5)" ---
# Context: Source Dialect Assumptions, TSV.
def test_exit_5_for_tsv_embedded_tab(ws):
    a = write(ws / "a.tsv", "id\tv\n1\ta\tb\n")
    res = run("--output", "-", "--key", "id", a)
    assert res.returncode == 5


# --- Spec: "nested fields trigger error 6" ---
# Context: Source Dialect Assumptions, Parquet.
def test_exit_6_for_nested_parquet(ws):
    pyarrow = pa()
    schema = pyarrow.schema([("id", pyarrow.int64()),
                             ("t", pyarrow.list_(pyarrow.int64()))])
    a = write_parquet(ws / "a.parquet", {"id": [1], "t": [[1]]}, schema=schema)
    res = run("--output", "-", "--key", "id", a)
    assert res.returncode == 6


# --- Spec: "objects must be flat (no arrays/objects as values)" ---
# Context: Source Dialect Assumptions, JSONL; error 6 per the checklist.
def test_exit_6_for_nested_jsonl(ws):
    a = write(ws / "a.jsonl", '{"id": 1, "n": {"a": 1}}\n')
    res = run("--output", "-", "--key", "id", a)
    assert res.returncode == 6


# --- Spec: usage errors ---
# Context: Usage; argparse-level problems exit 2.
def test_exit_2_for_missing_required_flag(ws):
    a = write(ws / "a.csv", "id\n1\n")
    res = run("--key", "id", a)
    assert res.returncode == 2


# --- Spec: "<INPUT1> [<INPUT2> ...]" ---
# Context: Usage; a nonexistent input is an I/O failure (see T26).
def test_nonexistent_input_is_nonzero(ws):
    res = run("--output", "-", "--key", "id", str(ws / "nope.csv"))
    assert res.returncode != 0
    assert "error" in stderr_shape(res)


# --- Spec: "Exact exit codes and stderr message shape" ---
# Context: Determinism Checklist; diagnostics are prefixed with the program name.
def test_stderr_message_shape(ws):
    a = write(ws / "a.csv", "id\n1\n")
    res = run("--output", "-", "--key", "ghost", a)
    assert res.stderr.startswith("merge_files.py: error: ")
    assert res.stderr.endswith("\n")
