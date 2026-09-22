"""Spec section: Examples — the two documented invocations."""

import json

from conftest import header_of, rows_of


# Phrase: "python merge_files.py --output merged.csv --key id data/*.csv"
# Context: Examples. Infer schema from inputs, sort by id, write to file.
def test_example_infer_and_write_to_file(csv_file, run_tool, workdir):
    csv_file("data/a.csv", "id,note\n3,c\n1,a\n")
    csv_file("data/b.csv", "id,note\n2,b\n")
    result = run_tool(
        "--output", "merged.csv", "--key", "id", "data/a.csv", "data/b.csv"
    )
    assert result.returncode == 0, result.stderr
    assert (workdir / "merged.csv").read_text(encoding="utf-8") == (
        "id,note\n1,a\n2,b\n3,c\n"
    )


# Phrase: "--output - --key ts,id --desc --schema schema.json
#          --on-type-error coerce-null --memory-limit-mb 128 inputs/*.csv"
# Context: Examples. Every flag of the second example together.
def test_example_schema_composite_desc_to_stdout(csv_file, run_tool):
    csv_file(
        "schema.json",
        json.dumps(
            {
                "columns": [
                    {"name": "id", "type": "int"},
                    {"name": "ts", "type": "timestamp"},
                    {"name": "amount", "type": "float"},
                    {"name": "note", "type": "string"},
                    {"name": "is_active", "type": "bool"},
                ]
            }
        ),
    )
    csv_file(
        "inputs/a.csv",
        "id,ts,amount,note,is_active\n"
        "1,2024-07-01T12:00:00Z,2.5,first,1\n"
        "2,2024-07-01T09:00:00+00:00,oops,second,0\n",
    )
    csv_file(
        "inputs/b.csv",
        "id,ts,note\n3,2024-07-01T12:00:00Z,third\n",
    )
    result = run_tool(
        "--output", "-", "--key", "ts,id", "--desc", "--schema", "schema.json",
        "--on-type-error", "coerce-null", "--memory-limit-mb", "128",
        "inputs/a.csv", "inputs/b.csv",
    )
    assert result.returncode == 0, result.stderr
    assert header_of(result.stdout) == ["id", "ts", "amount", "note", "is_active"]
    assert rows_of(result.stdout) == [
        ["3", "2024-07-01T12:00:00Z", "", "third", ""],
        ["1", "2024-07-01T12:00:00Z", "2.5", "first", "true"],
        ["2", "2024-07-01T09:00:00Z", "", "second", "false"],
    ]


# Phrase: "python merge_files.py --output merged.csv --key ts,id --schema-strategy consensus
#          inputs/users.csv inputs/events.jsonl.gz inputs/metrics.parquet"
# Context: Examples. Mixed CSV + JSONL + Parquet, consensus inference, composite key.
def test_example_mixed_formats_with_consensus(
    csv_file, jsonl_file, parquet_file, gzipped, run_tool, workdir
):
    csv_file("inputs/users.csv", "ts,id,name\n2024-07-01T10:00:00Z,2,bo\n")
    gzipped(
        jsonl_file(
            "inputs/events.jsonl",
            [{"ts": "2024-07-01T09:00:00Z", "id": 1, "event": "login"}],
        )
    )
    parquet_file(
        "inputs/metrics.parquet",
        {"ts": ["2024-07-01T11:00:00Z"], "id": [3], "value": [2.5]},
    )
    result = run_tool(
        "--output", "merged.csv", "--key", "ts,id",
        "--schema-strategy", "consensus",
        "inputs/users.csv", "inputs/events.jsonl.gz", "inputs/metrics.parquet",
    )
    assert result.returncode == 0, result.stderr
    assert (workdir / "merged.csv").read_text(encoding="utf-8") == (
        "event,id,name,ts,value\n"
        "login,1,,2024-07-01T09:00:00Z,\n"
        ",2,bo,2024-07-01T10:00:00Z,\n"
        ",3,,2024-07-01T11:00:00Z,2.5\n"
    )


# Phrase: "--output - --key created_at,id --desc --schema schema.json
#          --input-format tsv --compression gzip data/*.tsv.gz"
# Context: Examples. A provided schema over forced-format, forced-gzip TSV sources.
def test_example_authoritative_schema_over_gzipped_tsv(
    csv_file, tsv_file, gzipped, run_tool
):
    csv_file(
        "schema.json",
        json.dumps(
            {
                "columns": [
                    {"name": "created_at", "type": "timestamp"},
                    {"name": "id", "type": "int"},
                    {"name": "label", "type": "string"},
                ]
            }
        ),
    )
    gzipped(tsv_file("data/a.tsv", "created_at\tid\tlabel\n2024-07-01T09:00:00Z\t1\tay\n"))
    gzipped(tsv_file("data/b.tsv", "created_at\tid\tlabel\n2024-07-01T11:00:00Z\t2\tbee\n"))
    result = run_tool(
        "--output", "-", "--key", "created_at,id", "--desc",
        "--schema", "schema.json",
        "--input-format", "tsv", "--compression", "gzip",
        "data/a.tsv.gz", "data/b.tsv.gz",
    )
    assert result.returncode == 0, result.stderr
    assert header_of(result.stdout) == ["created_at", "id", "label"]
    assert rows_of(result.stdout) == [
        ["2024-07-01T11:00:00Z", "2", "bee"],
        ["2024-07-01T09:00:00Z", "1", "ay"],
    ]
