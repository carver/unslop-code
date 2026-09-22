"""Spec sections: Casting, Sorting and Stability, Output, Performance (mixed sources)."""
import datetime

import pytest

from conftest import body, header


# Phrase: "Mixed CSV + JSONL + Parquet, schema inferred by consensus, sort by composite key"
# Context: Examples; the documented invocation shape must work end to end.
def test_documented_mixed_example(run, work):
    work.csv(
        "users.csv", ["id", "ts", "name"], [["4", "2024-07-01T00:00:00Z", "ann"]]
    )
    work.gzip(
        "events.jsonl.gz",
        '{"id": 5, "ts": "2024-07-01T12:00:00Z", "kind": "click"}\n',
    )
    work.parquet(
        "metrics.parquet", [{"id": 6, "ts": "2024-07-02T00:00:00Z", "value": 1.5}]
    )
    r = run(
        "--output", "-", "--key", "ts,id", "--schema-strategy", "consensus",
        work.path("users.csv"), work.path("events.jsonl.gz"),
        work.path("metrics.parquet"),
    )
    assert r.ok, r.stderr
    assert header(r) == ["id", "kind", "name", "ts", "value"]
    assert body(r) == [
        ["4", "", "ann", "2024-07-01T00:00:00Z", ""],
        ["5", "click", "", "2024-07-01T12:00:00Z", ""],
        ["6", "", "", "2024-07-02T00:00:00Z", "1.5"],
    ]


# Phrase: "Sorting by `--key` uses casted key values"
# Context: Sorting and Stability; numeric order across formats, not text order.
def test_sort_uses_casted_values_across_formats(run, work):
    work.csv("a.csv", ["id"], [["100"]])
    work.jsonl("b.jsonl", [{"id": 9}])
    work.parquet("c.parquet", [{"id": 20}])
    r = run(
        "--output", "-", "--key", "id",
        work.path("a.csv"), work.path("b.jsonl"), work.path("c.parquet"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["9"], ["20"], ["100"]]


# Phrase: "Sort must be stable for equal keys"
# Context: Sorting and Stability; command-line order, then row order within a file.
def test_stability_across_mixed_sources(run, work):
    work.csv("a.csv", ["k", "tag"], [["7", "a1"], ["7", "a2"]])
    work.jsonl("b.jsonl", [{"k": 7, "tag": "b1"}, {"k": 7, "tag": "b2"}])
    work.parquet("c.parquet", [{"k": 7, "tag": "c1"}, {"k": 7, "tag": "c2"}])
    r = run(
        "--output", "-", "--key", "k",
        work.path("a.csv"), work.path("b.jsonl"), work.path("c.parquet"),
    )
    assert r.ok, r.stderr
    assert [row[1] for row in body(r)] == ["a1", "a2", "b1", "b2", "c1", "c2"]


# Phrase: "[--desc]"
# Context: Sorting; descending applies across mixed sources.
def test_desc_across_mixed_sources(run, work):
    work.csv("a.csv", ["id"], [["100"]])
    work.jsonl("b.jsonl", [{"id": 9}])
    work.parquet("c.parquet", [{"id": 20}])
    r = run(
        "--output", "-", "--key", "id", "--desc",
        work.path("a.csv"), work.path("b.jsonl"), work.path("c.parquet"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["100"], ["20"], ["9"]]


# Phrase: "All rows from all inputs appear exactly once; no deduplication"
# Context: Output.
def test_no_deduplication_across_formats(run, work):
    work.csv("a.csv", ["id"], [["5"], ["5"]])
    work.jsonl("b.jsonl", [{"id": 5}])
    work.parquet("c.parquet", [{"id": 5}])
    r = run(
        "--output", "-", "--key", "id",
        work.path("a.csv"), work.path("b.jsonl"), work.path("c.parquet"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["5"], ["5"], ["5"], ["5"]]


# Phrase: "Always produce single CSV with header row in resolved column order"
# Context: Output; parquet/jsonl inputs still yield CSV.
def test_output_is_csv_even_for_non_csv_inputs(run, work):
    work.parquet("a.parquet", [{"id": 2, "note": "x,y"}])
    r = run("--output", "-", "--key", "id", work.path("a.parquet"))
    assert r.ok, r.stderr
    assert r.stdout == 'id,note\n2,"x,y"\n'


# Phrase: "`--output -` writes to stdout; otherwise write atomically"
# Context: Output.
def test_output_file_written_completely(run, work):
    work.jsonl("a.jsonl", [{"id": 3}, {"id": 2}])
    out = work.path("merged.csv")
    r = run("--output", out, "--key", "id", work.path("a.jsonl"))
    assert r.ok, r.stderr
    assert out.read_text(encoding="utf-8") == "id\n2\n3\n"


def test_output_file_replaces_existing(run, work):
    work.write("merged.csv", "stale contents\n")
    work.jsonl("a.jsonl", [{"id": 3}])
    out = work.path("merged.csv")
    r = run("--output", out, "--key", "id", work.path("a.jsonl"))
    assert r.ok, r.stderr
    assert out.read_text(encoding="utf-8") == "id\n3\n"


def test_failed_run_leaves_no_output_file(run, work):
    work.jsonl("a.jsonl", [{"id": 3, "bad": [1]}])
    out = work.path("merged.csv")
    r = run("--output", out, "--key", "id", work.path("a.jsonl"))
    assert r.returncode == 6
    assert not out.exists()


def test_failed_run_leaves_previous_output_untouched(run, work):
    work.write("merged.csv", "previous\n")
    work.jsonl("a.jsonl", [{"id": 3, "bad": {"k": 1}}])
    out = work.path("merged.csv")
    r = run("--output", out, "--key", "id", work.path("a.jsonl"))
    assert r.returncode == 6
    assert out.read_text(encoding="utf-8") == "previous\n"


def test_no_temp_files_left_beside_output(run, work):
    work.jsonl("a.jsonl", [{"id": 3}, {"id": 2}])
    out = work.path("sub/merged.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    r = run("--output", out, "--key", "id", work.path("a.jsonl"))
    assert r.ok, r.stderr
    assert [p.name for p in out.parent.iterdir()] == ["merged.csv"]


# Phrase: "Use configured CSV dialect flags for output quoting/escaping and chosen
#          null literal"
# Context: Output.
def test_output_uses_configured_quotechar(run, work):
    work.jsonl("a.jsonl", [{"id": 2, "note": "x,y"}])
    r = run(
        "--output", "-", "--key", "id", "--csv-quotechar", "'", work.path("a.jsonl")
    )
    assert r.ok, r.stderr
    assert r.stdout == "id,note\n2,'x,y'\n"


def test_output_uses_configured_null_literal(run, work):
    work.jsonl("a.jsonl", [{"id": 2, "note": None}])
    r = run(
        "--output", "-", "--key", "id", "--csv-null-literal", "\\N",
        work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert r.stdout == "id,note\n2,\\N\n"


# Phrase: "Apply target output schema cast rules to every cell"
# Context: Casting; a provided schema recasts values from every source.
def test_schema_cast_applies_to_all_sources(run, work):
    work.schema("s.json", [("id", "int"), ("flag", "bool"), ("ts", "timestamp")])
    work.csv("a.csv", ["id", "flag", "ts"], [["1", "1", "2024-07-01 08:00:00+02:00"]])
    work.jsonl("b.jsonl", [{"id": 2, "flag": False, "ts": "2024-07-01T07:00:00Z"}])
    work.parquet(
        "c.parquet",
        [{"id": 3, "flag": True, "ts": datetime.datetime(2024, 7, 1, 9, 0, 0)}],
    )
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        work.path("a.csv"), work.path("b.jsonl"), work.path("c.parquet"),
    )
    assert r.ok, r.stderr
    assert body(r) == [
        ["1", "true", "2024-07-01T06:00:00Z"],
        ["2", "false", "2024-07-01T07:00:00Z"],
        ["3", "true", "2024-07-01T09:00:00Z"],
    ]


# Phrase: "On cast failure, follow `--on-type-error` from checkpoint 1"
# Context: Casting; applies to typed sources too.
def test_on_type_error_fail_on_jsonl_value(run, work):
    work.schema("s.json", [("id", "int"), ("n", "int")])
    work.jsonl("a.jsonl", [{"id": 1, "n": "oops"}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--on-type-error", "fail", work.path("a.jsonl"),
    )
    assert r.returncode != 0
    assert r.stdout == ""


def test_on_type_error_keep_string_on_jsonl_value(run, work):
    work.schema("s.json", [("id", "int"), ("n", "int")])
    work.jsonl("a.jsonl", [{"id": 1, "n": "oops"}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--on-type-error", "keep-string", work.path("a.jsonl"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", "oops"]]


def test_on_type_error_coerce_null_on_parquet_value(run, work):
    work.schema("s.json", [("id", "int"), ("n", "int")])
    work.parquet("a.parquet", [{"id": 1, "n": "oops"}])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--csv-null-literal", "NULL", work.path("a.parquet"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", "NULL"]]


# Phrase: "Implementation must work with `--memory-limit-mb` as low as 64 and
#          terabyte-scale inputs"
# Context: Performance & Memory; mixed sources under a small budget.
def test_mixed_sources_under_small_memory_limit(run, work):
    n = 4000
    work.csv("a.csv", ["id", "pad"], [[str(3 * i), "x" * 16] for i in range(n)])
    work.jsonl(
        "b.jsonl", [{"id": 3 * i + 1, "pad": "y" * 16} for i in range(n)]
    )
    work.parquet(
        "c.parquet", [{"id": 3 * i + 2, "pad": "z" * 16} for i in range(n)]
    )
    r = run(
        "--output", "-", "--key", "id", "--memory-limit-mb", "64",
        work.path("a.csv"), work.path("b.jsonl"), work.path("c.parquet"),
        timeout=300,
    )
    assert r.ok, r.stderr
    ids = [int(row[0]) for row in body(r)]
    assert ids == list(range(3 * n))


# Phrase: "Avoid format-specific issues (e.g., don't load entire Parquet files ...)"
# Context: Performance & Memory; a parquet file far larger than the memory budget.
def test_parquet_larger_than_memory_limit(run, work):
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    n = 60000
    rows = {
        "id": list(range(n, 0, -1)),
        "pad": ["p" * 64] * n,
    }
    table = pa.table(rows)
    path = work.path("big.parquet")
    pq.write_table(table, str(path), row_group_size=2000)
    r = run(
        "--output", work.path("out.csv"), "--key", "id",
        "--memory-limit-mb", "64", "--parquet-row-group-bytes", "65536",
        path, timeout=600,
    )
    assert r.ok, r.stderr
    with open(work.path("out.csv"), encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    assert lines[0] == "id,pad"
    assert len(lines) == n + 1
    assert lines[1].split(",")[0] == "1"
