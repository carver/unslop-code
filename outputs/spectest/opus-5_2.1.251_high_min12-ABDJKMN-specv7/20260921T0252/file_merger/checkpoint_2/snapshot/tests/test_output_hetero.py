"""Checkpoint 2 - Output section: single CSV, atomicity, dialect flags."""
import os

from conftest import (HAVE_PARQUET, needs_parquet, parse_csv,
                      parse_csv_dialect, run_tool, write_csv, write_file,
                      write_jsonl, write_parquet, write_schema, write_tsv,
                      body, col)


# --------------------------------------------------------------------------
# Phrase: "Always produce single CSV with header row in resolved column order"
# Context: Output.
# --------------------------------------------------------------------------
def test_output_is_csv_even_for_tsv_inputs(tmp_path):
    a = write_tsv(tmp_path / "a.tsv", ["id\tname", "7\tx"])
    res = run_tool("--output", "-", "--key", "id", a)
    assert res.returncode == 0, res.stderr
    assert res.stdout == "id,name\n7,x\n"


@needs_parquet
def test_output_is_csv_for_parquet_inputs(tmp_path):
    a = write_parquet(tmp_path / "a.parquet", {"id": [1], "name": ["x"]})
    res = run_tool("--output", "-", "--key", "id", a)
    assert res.returncode == 0, res.stderr
    assert res.stdout == "id,name\n1,x\n"


def test_header_row_uses_resolved_column_order(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("b", "string"), ("a", "string")])
    src = write_jsonl(tmp_path / "a.jsonl", [{"a": "1", "b": "2"}])
    res = run_tool("--output", "-", "--key", "a", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert res.rows()[0] == ["b", "a"]


def test_header_emitted_even_with_no_data_rows(tmp_path):
    schema = write_schema(tmp_path / "s.json", [("id", "int")])
    src = write_jsonl(tmp_path / "a.jsonl", [])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert res.stdout == "id\n"


def test_output_line_ending_is_newline(tmp_path):
    a = write_tsv(tmp_path / "a.tsv", ["id", "1"])
    res = run_tool("--output", "-", "--key", "id", a)
    assert res.returncode == 0, res.stderr
    assert "\r\n" not in res.stdout
    assert res.stdout.endswith("\n")


# --------------------------------------------------------------------------
# Phrase: "All rows from all inputs appear exactly once; no deduplication"
# Context: Output.
# --------------------------------------------------------------------------
def test_identical_rows_are_all_kept(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id,v", "9,x", "9,x"])
    b = write_jsonl(tmp_path / "b.jsonl", [{"id": 9, "v": "x"}])
    res = run_tool("--output", "-", "--key", "id", a, b)
    assert res.returncode == 0, res.stderr
    assert body(res.rows()) == [["9", "x"]] * 3


@needs_parquet
def test_row_count_is_the_sum_over_all_inputs(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id"] + [str(i) for i in range(5)])
    b = write_jsonl(tmp_path / "b.jsonl", [{"id": i} for i in range(7)])
    c = write_parquet(tmp_path / "c.parquet", {"id": list(range(3))})
    res = run_tool("--output", "-", "--key", "id", a, b, c)
    assert res.returncode == 0, res.stderr
    assert len(body(res.rows())) == 15


# --------------------------------------------------------------------------
# Phrase: "--output - writes to stdout; otherwise write atomically"
# Context: Output.
# --------------------------------------------------------------------------
def test_output_dash_writes_stdout(tmp_path):
    a = write_jsonl(tmp_path / "a.jsonl", [{"id": 1}])
    res = run_tool("--output", "-", "--key", "id", a)
    assert res.returncode == 0, res.stderr
    assert res.stdout.startswith("id\n")
    assert not (tmp_path / "-").exists()


def test_output_path_receives_the_csv(tmp_path):
    a = write_jsonl(tmp_path / "a.jsonl", [{"id": 6, "v": "x"}])
    out = tmp_path / "merged.csv"
    res = run_tool("--output", str(out), "--key", "id", a)
    assert res.returncode == 0, res.stderr
    assert res.stdout == ""
    assert open(str(out)).read() == "id,v\n6,x\n"


def test_failed_run_leaves_previous_output_intact(tmp_path):
    # Atomic write: a run that dies partway must not truncate the target.
    out = tmp_path / "merged.csv"
    write_file(out, "PREVIOUS\n")
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("n", "int")])
    a = write_jsonl(tmp_path / "a.jsonl",
                    [{"id": i, "n": "abc"} for i in range(200)])
    res = run_tool("--output", str(out), "--key", "id", "--schema", schema,
                   "--on-type-error", "fail", a)
    assert res.returncode != 0
    assert open(str(out)).read() == "PREVIOUS\n"


def test_failed_run_creates_no_output_file(tmp_path):
    out = tmp_path / "merged.csv"
    a = write_csv(tmp_path / "a.csv", ["id", "1"])
    res = run_tool("--output", str(out), "--key", "nope", a)
    assert res.returncode == 3
    assert not out.exists()


def test_no_stray_temp_files_left_behind(tmp_path):
    outdir = tmp_path / "out"
    outdir.mkdir()
    a = write_jsonl(tmp_path / "a.jsonl", [{"id": 1}])
    out = outdir / "merged.csv"
    res = run_tool("--output", str(out), "--key", "id", a)
    assert res.returncode == 0, res.stderr
    assert sorted(os.listdir(str(outdir))) == ["merged.csv"]


def test_output_overwrites_existing_file(tmp_path):
    out = tmp_path / "merged.csv"
    write_file(out, "OLD CONTENT THAT IS MUCH LONGER\n")
    a = write_jsonl(tmp_path / "a.jsonl", [{"id": 3}])
    res = run_tool("--output", str(out), "--key", "id", a)
    assert res.returncode == 0, res.stderr
    assert open(str(out)).read() == "id\n3\n"


# --------------------------------------------------------------------------
# Phrase: "Use configured CSV dialect flags for output quoting/escaping and
#          chosen null literal"
# Context: Output.
# --------------------------------------------------------------------------
def test_output_uses_configured_quotechar(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("v", "string")])
    a = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "v": "x,y"}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--csv-quotechar", "'", a)
    assert res.returncode == 0, res.stderr
    assert res.stdout == "id,v\n1,'x,y'\n"


def test_output_doubles_the_configured_quotechar(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("v", "string")])
    a = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "v": "it's,here"}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--csv-quotechar", "'", a)
    assert res.returncode == 0, res.stderr
    rows = parse_csv_dialect(res.stdout, quotechar="'")
    assert col(rows, "v") == ["it's,here"]


def test_default_output_quoting_is_rfc4180(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("v", "string")])
    a = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "v": 'a"b,c'}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, a)
    assert res.returncode == 0, res.stderr
    assert res.stdout == 'id,v\n1,"a""b,c"\n'


def test_output_null_literal_applies_to_every_source(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("v", "string")])
    a = write_csv(tmp_path / "a.csv", ["id,v", "1,"])
    b = write_tsv(tmp_path / "b.tsv", ["id\tv", "2\t"])
    c = write_jsonl(tmp_path / "c.jsonl", [{"id": 3, "v": None}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--csv-null-literal", "\\N", a, b, c)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == ["\\N", "\\N", "\\N"]


def test_null_literal_needing_quotes_is_quoted(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("v", "string")])
    a = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "v": None}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema,
                   "--csv-null-literal", "a,b", a)
    assert res.returncode == 0, res.stderr
    assert res.stdout == 'id,v\n1,"a,b"\n'


def test_tab_in_value_from_jsonl_survives_to_csv(tmp_path):
    schema = write_schema(tmp_path / "s.json",
                          [("id", "int"), ("v", "string")])
    a = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "v": "a\tb"}])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, a)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "v") == ["a\tb"]
