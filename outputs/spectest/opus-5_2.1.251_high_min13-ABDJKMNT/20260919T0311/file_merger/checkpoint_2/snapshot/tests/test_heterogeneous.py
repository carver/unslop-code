"""Spec sections: Casting, Sorting and Stability, Output, Determinism Checklist.

These exercise the rules that only show up once several formats meet in one run.
"""
import datetime

import pyarrow as pa
from conftest import column, lines, table


# Phrase: "If --schema provided, it defines exact output columns, types, and order"
# Context: order is the schema's, not lexicographic, across mixed formats.
def test_explicit_schema_fixes_columns_and_order(run, csv_file, jsonl_file, schema_file):
    csv_file("a.csv", "id,v\n1,x\n")
    jsonl_file("b.jsonl", [{"id": 2, "v": "y"}])
    schema = schema_file([("v", "string"), ("id", "int")])
    res = run("--output", "-", "--key", "id", "--schema", schema, "a.csv", "b.jsonl")
    assert table(res.stdout) == [["v", "id"], ["x", "1"], ["y", "2"]]


# Phrase: "Extra input columns ignored; missing columns filled with null literal"
def test_schema_ignores_extras_and_fills_missing(run, csv_file, jsonl_file, schema_file):
    csv_file("a.csv", "id,extra\n1,drop\n")
    jsonl_file("b.jsonl", [{"id": 2}])
    schema = schema_file([("id", "int"), ("absent", "string")])
    res = run("--output", "-", "--key", "id", "--schema", schema,
              "--csv-null-literal", "NA", "a.csv", "b.jsonl")
    assert table(res.stdout) == [["id", "absent"], ["1", "NA"], ["2", "NA"]]


# Phrase: "Sorting by --key uses casted key values"
# Context: an int key from three formats orders numerically, not lexicographically.
def test_sorting_uses_casted_key_values(run, csv_file, jsonl_file, parquet_file):
    csv_file("a.csv", "id\n100\n")
    jsonl_file("b.jsonl", [{"id": 9}])
    parquet_file("c.parquet", {"id": ([10], pa.int64())})
    res = run("--output", "-", "--key", "id", "a.csv", "b.jsonl", "c.parquet")
    assert column(res.stdout, "id") == ["9", "10", "100"]


# Phrase: "Keys must exist in resolved schema (error 3 otherwise)"
def test_missing_key_column_is_error_3(run, jsonl_file):
    jsonl_file("a.jsonl", [{"id": 1}])
    res = run("--output", "-", "--key", "nope", "a.jsonl")
    assert res.returncode == 3
    assert res.stderr.strip().startswith("error:")


# Phrase: "Keys must exist in resolved schema (error 3 otherwise)"
# Context: the check is against the resolved schema, so a column present in the
#   input but absent from an explicit --schema is still an error.
def test_key_outside_explicit_schema_is_error_3(run, csv_file, schema_file):
    csv_file("a.csv", "id,v\n1,x\n")
    schema = schema_file([("id", "int")])
    res = run("--output", "-", "--key", "v", "--schema", schema, "a.csv")
    assert res.returncode == 3


# Phrase: "Sort must be stable for equal keys"
# Context: equal keys keep input order, and files are read in command-line order.
def test_stability_across_mixed_sources(run, csv_file, jsonl_file, parquet_file):
    jsonl_file("a.jsonl", [{"k": 1, "seq": "j1"}, {"k": 1, "seq": "j2"}])
    csv_file("b.csv", "k,seq\n1,c1\n1,c2\n")
    parquet_file("c.parquet", {"k": ([1, 1], pa.int64()), "seq": (["p1", "p2"], pa.string())})
    res = run("--output", "-", "--key", "k", "a.jsonl", "b.csv", "c.parquet")
    assert column(res.stdout, "seq") == ["j1", "j2", "c1", "c2", "p1", "p2"]


# Phrase: "Sort must be stable for equal keys" with "[--desc]"
# Context: descending inverts the key order only; ties keep input order.
def test_descending_is_still_stable(run, csv_file, jsonl_file):
    jsonl_file("a.jsonl", [{"k": 1, "seq": "j1"}, {"k": 2, "seq": "j2"}])
    csv_file("b.csv", "k,seq\n1,c1\n")
    res = run("--output", "-", "--key", "k", "--desc", "a.jsonl", "b.csv")
    assert column(res.stdout, "seq") == ["j2", "j1", "c1"]


# Phrase: "--key <col>[,<col>...]"
# Context: a composite key compares the columns left to right.
def test_composite_key_across_formats(run, csv_file, jsonl_file):
    csv_file("a.csv", "ts,id,src\n2024-07-01T00:00:00Z,2,csv\n")
    jsonl_file("b.jsonl", [{"ts": "2024-07-01T00:00:00Z", "id": 1, "src": "jsonl"},
                           {"ts": "2024-06-01T00:00:00Z", "id": 9, "src": "early"}])
    res = run("--output", "-", "--key", "ts,id", "--schema-strategy", "union",
              "a.csv", "b.jsonl")
    assert column(res.stdout, "src") == ["early", "jsonl", "csv"]


# Phrase: "All rows from all inputs appear exactly once; no deduplication"
def test_identical_rows_are_all_kept(run, csv_file, jsonl_file):
    csv_file("a.csv", "id,v\n1,x\n1,x\n")
    jsonl_file("b.jsonl", [{"id": 1, "v": "x"}])
    res = run("--output", "-", "--key", "id", "a.csv", "b.jsonl")
    assert table(res.stdout)[1:] == [["1", "x"]] * 3


# Phrase: "Always produce single CSV with header row in resolved column order"
# Context: whatever the input formats were, the output is CSV.
def test_output_is_csv_even_for_non_csv_inputs(run, jsonl_file):
    jsonl_file("a.jsonl", [{"id": 1, "v": "a,b"}])
    res = run("--output", "-", "--key", "id", "a.jsonl")
    assert lines(res.stdout) == ["id,v", '1,"a,b"']


# Phrase: "Use configured CSV dialect flags for output quoting/escaping and chosen null literal"
# Context: the null literal chosen on the command line is what missing cells render as.
def test_configured_null_literal_is_used_on_output(run, jsonl_file):
    jsonl_file("a.jsonl", [{"id": 1, "v": None}, {"id": 2}])
    res = run("--output", "-", "--key", "id", "--csv-null-literal", "\\N", "a.jsonl")
    assert column(res.stdout, "v") == ["\\N", "\\N"]


# Phrase: "--output - writes to stdout; otherwise write atomically"
# Context: T36 — a run that fails partway leaves any pre-existing file intact.
def test_failed_run_does_not_clobber_the_output_file(run, tmp_path, jsonl_file, schema_file):
    (tmp_path / "out.csv").write_text("previous\n", encoding="utf-8")
    jsonl_file("a.jsonl", [{"id": 1, "n": "nope"}])
    schema = schema_file([("id", "int"), ("n", "int")])
    res = run("--output", "out.csv", "--key", "id", "--schema", schema,
              "--on-type-error", "fail", "a.jsonl")
    assert res.returncode != 0
    assert (tmp_path / "out.csv").read_text(encoding="utf-8") == "previous\n"


# Phrase: "On cast failure, follow --on-type-error from checkpoint 1"
# Context: keep-string echoes the original text of a typed value too.
def test_keep_string_on_a_typed_value(run, jsonl_file, schema_file):
    jsonl_file("a.jsonl", [{"id": 1, "n": True}])
    schema = schema_file([("id", "int"), ("n", "int")])
    res = run("--output", "-", "--key", "id", "--schema", schema,
              "--on-type-error", "keep-string", "a.jsonl")
    assert column(res.stdout, "n") == ["true"]


# Phrase: "On cast failure, follow --on-type-error from checkpoint 1"
# Context: T20 — fail exits 4 and says why.
def test_fail_mode_on_a_typed_value_is_error_4(run, jsonl_file, schema_file):
    jsonl_file("a.jsonl", [{"id": 1, "n": "abc"}])
    schema = schema_file([("id", "int"), ("n", "int")])
    res = run("--output", "-", "--key", "id", "--schema", schema,
              "--on-type-error", "fail", "a.jsonl")
    assert res.returncode == 4
    assert res.stderr.strip().startswith("error:")


# Phrase: "Implementation must work with --memory-limit-mb as low as 64 and
#   terabyte-scale inputs"
# Context: a mixed run under a 1MB budget still spills, merges and sorts.
def test_mixed_sources_spill_and_sort(run, tmp_path):
    import json

    import pyarrow.parquet as pq

    with open(tmp_path / "a.csv", "w", encoding="utf-8") as fh:
        fh.write("id,pad\n")
        for i in range(3000):
            fh.write(f"{i * 3},{'x' * 100}\n")
    with open(tmp_path / "b.jsonl", "w", encoding="utf-8") as fh:
        for i in range(3000):
            fh.write(json.dumps({"id": i * 3 + 1, "pad": "y" * 100}) + "\n")
    pq.write_table(
        pa.table({"id": pa.array([i * 3 + 2 for i in range(3000)], pa.int64()),
                  "pad": pa.array(["z" * 100] * 3000, pa.string())}),
        tmp_path / "c.parquet", row_group_size=100,
    )
    res = run("--output", "out.csv", "--key", "id", "--memory-limit-mb", "1",
              "a.csv", "b.jsonl", "c.parquet")
    assert res.returncode == 0, res.stderr
    with open(tmp_path / "out.csv", encoding="utf-8") as fh:
        assert fh.readline() == "id,pad\n"
        ids = [int(line.split(",", 1)[0]) for line in fh]
    assert ids == list(range(9000))


# Phrase: "Apply target output schema cast rules to every cell"
# Context: a Parquet timestamp and a CSV timestamp string land in the same column.
def test_timestamps_normalise_across_formats(run, csv_file, parquet_file):
    csv_file("a.csv", "id,t\n1,2024-07-01T14:00:00+02:00\n")
    parquet_file("b.parquet", {
        "id": ([2], pa.int64()),
        "t": ([datetime.datetime(2024, 7, 1, 9, 0, 0)], pa.timestamp("s")),
    })
    res = run("--output", "-", "--key", "t", "--schema-strategy", "union", "a.csv", "b.parquet")
    assert column(res.stdout, "t") == ["2024-07-01T09:00:00Z", "2024-07-01T12:00:00Z"]
