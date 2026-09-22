"""Sorting, stability and output rules with heterogeneous inputs."""

import datetime as dt
import json

import pytest


@pytest.fixture
def schema_file(tmp_path):
    def _write(columns, name="schema.json"):
        path = tmp_path / name
        path.write_text(json.dumps({"columns": columns}), encoding="utf-8")
        return path

    return _write


# --- Sorting and stability -------------------------------------------------


def test_sorting_uses_casted_key_values(run_cli, csv_file, jsonl_file):
    # Spec: "Sorting by `--key` uses casted key values"
    a = csv_file("a.csv", "id\n10\n9\n")
    b = jsonl_file("b.jsonl", [{"id": 100}])
    result = run_cli("--output", "-", "--key", "id", a, b)
    assert result.returncode == 0, result.stderr
    assert result.rows == [["id"], ["9"], ["10"], ["100"]]


def test_composite_key_across_mixed_sources(run_cli, csv_file, jsonl_file, parquet_file):
    # Spec: "--key ts,id" example: "Mixed CSV + JSONL + Parquet ... sort by composite key"
    a = csv_file("a.csv", "ts,id\n2024-07-02T00:00:00,2\n")
    b = jsonl_file("b.jsonl", [{"ts": "2024-07-01T00:00:00", "id": 5}])
    c = parquet_file("c.parquet", {"ts": [dt.datetime(2024, 7, 1)], "id": [1]})
    result = run_cli("--output", "-", "--key", "ts,id", a, b, c)
    assert result.returncode == 0, result.stderr
    assert result.rows == [
        ["id", "ts"],
        ["1", "2024-07-01T00:00:00Z"],
        ["5", "2024-07-01T00:00:00Z"],
        ["2", "2024-07-02T00:00:00Z"],
    ]


def test_sort_is_stable_across_sources(run_cli, csv_file, jsonl_file):
    # Spec: "Sort must be stable for equal keys"
    a = csv_file("a.csv", "k,tag\n1,a1\n1,a2\n")
    b = jsonl_file("b.jsonl", [{"k": 1, "tag": "b1"}])
    result = run_cli("--output", "-", "--key", "k", a, b)
    assert [row[1] for row in result.rows[1:]] == ["a1", "a2", "b1"]


def test_stability_holds_under_desc(run_cli, csv_file, jsonl_file):
    # Spec: "[--desc]" + "Sort must be stable for equal keys" (AMBIGUITIES T10)
    a = csv_file("a.csv", "k,tag\n1,a1\n1,a2\n")
    b = jsonl_file("b.jsonl", [{"k": 1, "tag": "b1"}])
    result = run_cli("--output", "-", "--key", "k", "--desc", a, b)
    assert [row[1] for row in result.rows[1:]] == ["a1", "a2", "b1"]


def test_desc_reverses_mixed_source_order(run_cli, csv_file, parquet_file):
    # Spec usage: "[--desc]" applied to a merge of mixed sources
    a = csv_file("a.csv", "id\n1\n3\n")
    b = parquet_file("b.parquet", {"id": [2, 4]})
    result = run_cli("--output", "-", "--key", "id", "--desc", a, b)
    assert result.rows == [["id"], ["4"], ["3"], ["2"], ["1"]]


def test_key_absent_from_resolved_schema_is_error_3(run_cli, jsonl_file):
    # Spec: "Keys must exist in resolved schema (error 3 otherwise)"
    a = jsonl_file("a.jsonl", [{"id": 1}])
    result = run_cli("--output", "-", "--key", "missing", a)
    assert result.returncode == 3
    assert "missing" in result.stderr


def test_key_absent_from_provided_schema_is_error_3(run_cli, jsonl_file, schema_file):
    # Spec: "Keys must exist in resolved schema (error 3 otherwise)"
    schema = schema_file([{"name": "id", "type": "int"}])
    a = jsonl_file("a.jsonl", [{"id": 1, "other": 2}])
    result = run_cli("--output", "-", "--key", "other", "--schema", schema, a)
    assert result.returncode == 3


# --- Output ----------------------------------------------------------------


def test_single_csv_with_header_in_resolved_order(run_cli, csv_file, jsonl_file, parquet_file):
    # Spec: "Always produce single CSV with header row in resolved column order"
    a = csv_file("a.csv", "id,b\n1,x\n")
    b = jsonl_file("b.jsonl", [{"id": 2, "a": "y"}])
    c = parquet_file("c.parquet", {"id": [3], "c": ["z"]})
    result = run_cli("--output", "-", "--key", "id", a, b, c)
    assert result.rows == [
        ["a", "b", "c", "id"],
        ["", "x", "", "1"],
        ["y", "", "", "2"],
        ["", "", "z", "3"],
    ]


def test_every_row_appears_once_without_deduplication(run_cli, csv_file, jsonl_file):
    # Spec: "All rows from all inputs appear exactly once; no deduplication"
    a = csv_file("a.csv", "id,note\n1,dup\n1,dup\n")
    b = jsonl_file("b.jsonl", [{"id": 1, "note": "dup"}])
    result = run_cli("--output", "-", "--key", "id", a, b)
    assert result.rows[1:] == [["1", "dup"]] * 3


def test_output_dash_writes_stdout_for_mixed_inputs(run_cli, jsonl_file, parquet_file):
    # Spec: "`--output -` writes to stdout"
    a = jsonl_file("a.jsonl", [{"id": 2}])
    b = parquet_file("b.parquet", {"id": [1]})
    result = run_cli("--output", "-", "--key", "id", a, b)
    assert result.stdout == "id\n1\n2\n"


def test_output_path_is_written_without_leftover_temp_files(run_cli, jsonl_file, tmp_path):
    # Spec: "otherwise write atomically" (AMBIGUITIES T29)
    a = jsonl_file("a.jsonl", [{"id": 1}])
    out = tmp_path / "out" / "merged.csv"
    out.parent.mkdir()
    result = run_cli("--output", out, "--key", "id", a)
    assert result.returncode == 0, result.stderr
    assert out.read_text(encoding="utf-8") == "id\n1\n"
    assert [p.name for p in out.parent.iterdir()] == ["merged.csv"]


def test_failed_run_leaves_existing_output_untouched(run_cli, jsonl_file, schema_file, tmp_path):
    # Spec: "write atomically" — a failing run must not replace or truncate the target
    schema = schema_file([{"name": "id", "type": "int"}, {"name": "n", "type": "int"}])
    a = jsonl_file("a.jsonl", [{"id": 1, "n": 2.5}])
    out = tmp_path / "out" / "merged.csv"
    out.parent.mkdir()
    out.write_text("PREVIOUS\n", encoding="utf-8")
    result = run_cli("--output", out, "--key", "id", "--schema", schema, "--on-type-error", "fail", a)
    assert result.returncode == 4
    assert out.read_text(encoding="utf-8") == "PREVIOUS\n"
    assert [p.name for p in out.parent.iterdir()] == ["merged.csv"]


def test_output_uses_configured_quotechar(run_cli, jsonl_file):
    # Spec: "Use configured CSV dialect flags for output quoting/escaping"
    a = jsonl_file("a.jsonl", [{"id": 1, "note": "a,b"}])
    result = run_cli("--output", "-", "--key", "id", "--csv-quotechar", "'", a)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "id,note\n1,'a,b'\n"


def test_output_uses_configured_escapechar(run_cli, jsonl_file):
    # Spec: "Use configured CSV dialect flags for output quoting/escaping"
    a = jsonl_file("a.jsonl", [{"id": 1, "note": 'a"b'}])
    result = run_cli("--output", "-", "--key", "id", "--csv-escapechar", "\\", a)
    assert result.returncode == 0, result.stderr
    assert result.stdout == 'id,note\n1,a\\"b\n'


def test_output_uses_chosen_null_literal_for_all_sources(run_cli, csv_file, jsonl_file, parquet_file):
    # Spec: "Use configured CSV dialect flags ... and chosen null literal"
    a = csv_file("a.csv", "id,note\n1,\n")
    b = jsonl_file("b.jsonl", [{"id": 2, "note": None}])
    c = parquet_file("c.parquet", {"id": [3], "note": [None]})
    result = run_cli("--output", "-", "--key", "id", "--csv-null-literal", "\\N", a, b, c)
    assert result.rows[1:] == [["1", "\\N"], ["2", "\\N"], ["3", "\\N"]]


# --- Performance -----------------------------------------------------------


def test_low_memory_limit_still_sorts_all_rows(run_cli, csv_file, jsonl_file, parquet_file):
    # Spec: "Implementation must work with `--memory-limit-mb` as low as 64 and terabyte-scale inputs"
    a = csv_file("a.csv", "id\n" + "".join(f"{n}\n" for n in range(0, 3000, 3)))
    b = jsonl_file("b.jsonl", [{"id": n} for n in range(1, 3000, 3)])
    c = parquet_file("c.parquet", {"id": list(range(2, 3000, 3))})
    result = run_cli(
        "--output", "-", "--key", "id", "--memory-limit-mb", "64",
        "--parquet-row-group-bytes", "1024", a, b, c,
    )
    assert result.returncode == 0, result.stderr
    assert result.rows[1:] == [[str(n)] for n in range(3000)]


def test_temp_dir_is_used_for_spilled_runs(run_cli, csv_file, tmp_path):
    # Spec usage: "[--memory-limit-mb <INT>] [--temp-dir <PATH>]"
    spill = tmp_path / "spill"
    spill.mkdir()
    a = csv_file("a.csv", "id\n" + "".join(f"{n}\n" for n in range(2000, 0, -1)))
    result = run_cli("--output", "-", "--key", "id", "--memory-limit-mb", "1", "--temp-dir", spill, a)
    assert result.returncode == 0, result.stderr
    assert result.rows[1:] == [[str(n)] for n in range(1, 2001)]
