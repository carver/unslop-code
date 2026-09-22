"""Merging heterogeneous inputs: casting, sorting and output across formats."""

import datetime

import pyarrow as pa

from conftest import column, rows_of


# Spec: "Always produce single CSV with header row in resolved column order"
def test_single_csv_with_one_header_row(make_csv, make_jsonl, make_parquet, run):
    make_csv("a.csv", "id,v\n10,x\n")
    make_jsonl("b.jsonl", [{"id": 20, "v": "y"}])
    make_parquet("c.parquet", {"id": pa.array([30]), "v": pa.array(["z"])})
    rows = rows_of(run("--output", "-", "--key", "id", "a.csv", "b.jsonl", "c.parquet").stdout)
    assert rows[0] == ["id", "v"]
    assert len(rows) == 4


# Spec: "All rows from all inputs appear exactly once; no deduplication"
def test_duplicate_rows_across_formats_are_all_kept(make_csv, make_jsonl, run):
    make_csv("a.csv", "id\n5\n5\n")
    make_jsonl("b.jsonl", [{"id": 5}])
    proc = run("--output", "-", "--key", "id", "a.csv", "b.jsonl")
    assert rows_of(proc.stdout)[1:] == [["5"], ["5"], ["5"]]


# Spec: "Sorting by `--key` uses casted key values"
# Context: an int key drawn from three formats orders numerically, not by text.
def test_sorting_uses_casted_key_values_across_formats(make_csv, make_jsonl, make_parquet, run):
    make_csv("a.csv", "id\n100\n")
    make_jsonl("b.jsonl", [{"id": 9}])
    make_parquet("c.parquet", {"id": pa.array([20], pa.int64())})
    proc = run("--output", "-", "--key", "id", "a.csv", "b.jsonl", "c.parquet")
    assert rows_of(proc.stdout)[1:] == [["9"], ["20"], ["100"]]


# Spec: "Sort must be stable for equal keys"
# Context: ties keep command line order of the files and record order inside them.
def test_ties_keep_input_appearance_order_across_formats(make_csv, make_jsonl, make_parquet, run):
    make_csv("a.csv", "id,src\n1,csv1\n1,csv2\n")
    make_jsonl("b.jsonl", [{"id": 1, "src": "json"}])
    make_parquet("c.parquet", {"id": pa.array([1]), "src": pa.array(["parquet"])})
    rows = rows_of(run("--output", "-", "--key", "id", "a.csv", "b.jsonl", "c.parquet").stdout)
    assert column(rows, "src") == ["csv1", "csv2", "json", "parquet"]


# Spec: "Sort must be stable for equal keys" with "[--desc]"
def test_desc_reverses_keys_but_not_tie_order(make_csv, make_jsonl, run):
    make_csv("a.csv", "id,src\n5,csv\n6,csv\n")
    make_jsonl("b.jsonl", [{"id": 5, "src": "json"}])
    rows = rows_of(run("--output", "-", "--key", "id", "--desc", "a.csv", "b.jsonl").stdout)
    assert list(zip(column(rows, "id"), column(rows, "src"))) == [("6", "csv"), ("5", "csv"), ("5", "json")]


# Spec: "Mixed CSV + JSONL + Parquet, schema inferred by consensus, sort by composite key"
# Context: the spec's own example invocation.
def test_composite_key_over_mixed_inputs_with_consensus(make_csv, make_jsonl, make_parquet, gzipped, run):
    make_csv("users.csv", "ts,id\n2024-07-01T00:00:00Z,2\n2024-07-01T00:00:00Z,1\n")
    gzipped(make_jsonl("events.jsonl", [{"ts": "2024-06-30T23:00:00Z", "id": 5}]))
    make_parquet(
        "metrics.parquet",
        {"ts": pa.array([datetime.datetime(2024, 7, 2, 0, 0)], pa.timestamp("us", tz="UTC")), "id": pa.array([9])},
    )
    rows = rows_of(
        run(
            "--output", "-", "--key", "ts,id", "--schema-strategy", "consensus",
            "users.csv", "events.jsonl.gz", "metrics.parquet",
        ).stdout
    )
    assert column(rows, "id") == ["5", "1", "2", "9"]


# Spec: "Apply target output schema cast rules to every cell"
# Context: a provided schema retypes values that arrived typed from parquet/JSONL.
def test_provided_schema_casts_typed_values(make_jsonl, make_parquet, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "v": 2}])
    make_parquet("b.parquet", {"id": pa.array([2]), "v": pa.array([3], pa.int64())})
    make_schema("s.json", [("id", "int"), ("v", "float")])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "a.jsonl", "b.parquet")
    assert rows_of(proc.stdout)[1:] == [["1", "2.0"], ["2", "3.0"]]


# Spec: "On cast failure, follow `--on-type-error` from checkpoint 1"
# Context: keep-string preserves the text a typed value rendered to.
def test_on_type_error_keep_string_applies_to_typed_sources(make_jsonl, make_schema, run):
    make_jsonl("a.jsonl", [{"id": 1, "v": True}])
    make_schema("s.json", [("id", "int"), ("v", "date")])
    proc = run("--output", "-", "--key", "id", "--schema", "s.json", "--on-type-error", "keep-string", "a.jsonl")
    assert rows_of(proc.stdout)[1] == ["1", "true"]


# Spec: "On cast failure, follow `--on-type-error` from checkpoint 1"
def test_on_type_error_fail_stops_the_merge(make_parquet, make_schema, run):
    make_parquet("a.parquet", {"id": pa.array([1]), "v": pa.array(["abc"])})
    make_schema("s.json", [("id", "int"), ("v", "int")])
    proc = run(
        "--output", "-", "--key", "id", "--schema", "s.json", "--on-type-error", "fail",
        "a.parquet", expect_ok=False,
    )
    assert proc.returncode != 0
    assert proc.stderr.strip()


# Spec: "`--output -` writes to stdout; otherwise write atomically"
def test_named_output_is_written_and_stdout_stays_empty(make_jsonl, run, workdir):
    make_jsonl("a.jsonl", [{"id": 7}])
    proc = run("--output", "out.csv", "--key", "id", "a.jsonl")
    assert proc.stdout == ""
    assert (workdir / "out.csv").read_text() == "id\n7\n"


# Spec: "otherwise write atomically"
# Context: a run that fails part way leaves no partial output behind.
def test_failed_run_leaves_no_output_file(make_text, run, workdir):
    make_text("a.jsonl", '{"id": 1}\n{"id": 2, "bad": [1]}\n')
    proc = run("--output", "out.csv", "--key", "id", "a.jsonl", expect_ok=False)
    assert proc.returncode == 6
    assert not (workdir / "out.csv").exists()


# Spec: "Use configured CSV dialect flags for output quoting/escaping and chosen null literal"
# Context: see AMBIGUITIES T2/T33 - the flags now configure the writer too.
def test_output_quoting_uses_the_configured_quote_character(make_csv, run):
    make_csv("a.csv", "id,v\n7,'a,b'\n")
    proc = run("--output", "-", "--key", "id", "--csv-quotechar", "'", "a.csv")
    assert proc.stdout == "id,v\n7,'a,b'\n"


# Spec: "Use configured CSV dialect flags for output quoting/escaping"
# Context: see AMBIGUITIES T33 - the escape character escapes itself on output,
# so the result reads back through the same flags.
def test_output_escaping_uses_the_configured_escape_character(make_jsonl, run):
    make_jsonl("a.jsonl", [{"id": 7, "v": "c:\\tmp"}])
    proc = run("--output", "-", "--key", "id", "a.jsonl")
    assert proc.stdout == "id,v\n7,c:\\\\tmp\n"


# Spec: "Use configured CSV dialect flags for ... chosen null literal"
def test_null_literal_is_used_for_every_source_kind(make_csv, make_jsonl, make_parquet, run):
    make_csv("a.csv", "id,v\n1,\n")
    make_jsonl("b.jsonl", [{"id": 2, "v": None}])
    make_parquet("c.parquet", {"id": pa.array([3]), "v": pa.array([None], pa.string())})
    rows = rows_of(run("--output", "-", "--key", "id", "--csv-null-literal", "NULL", "a.csv", "b.jsonl", "c.parquet").stdout)
    assert column(rows, "v") == ["NULL", "NULL", "NULL"]


# Spec: "Implementation must work with `--memory-limit-mb` as low as 64 and terabyte-scale inputs"
# Context: the external sort keeps working when the inputs are heterogeneous.
def test_mixed_inputs_sort_correctly_while_spilling(make_text, make_parquet, run, workdir):
    import json

    make_text("a.jsonl", "".join(json.dumps({"id": i, "pad": "x" * 200}) + "\n" for i in range(0, 3000, 2)))
    make_parquet(
        "b.parquet",
        {"id": pa.array(list(range(1, 3000, 2))), "pad": pa.array(["y" * 200] * 1500)},
    )
    run("--output", "out.csv", "--key", "id", "--memory-limit-mb", "1", "a.jsonl", "b.parquet")
    rows = rows_of((workdir / "out.csv").read_text())
    assert [int(v) for v in column(rows, "id")] == list(range(3000))
