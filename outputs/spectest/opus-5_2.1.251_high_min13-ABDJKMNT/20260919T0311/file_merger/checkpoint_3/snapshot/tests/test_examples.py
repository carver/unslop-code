"""Spec section: Examples."""
import json

from conftest import table


# Phrase: "python merge_files.py --output merged.csv --key id data/*.csv"
# Context: infer schema from inputs, sort by id, write to file (the shell
#   expands the glob, so the tool sees a list of paths).
def test_example_infer_and_write_to_file(run, csv_file, tmp_path):
    csv_file("data/one.csv", "id,name\n3,c\n1,a\n")
    csv_file("data/two.csv", "id,name,extra\n2,b,e\n")
    res = run("--output", "merged.csv", "--key", "id", "data/one.csv", "data/two.csv")
    assert res.returncode == 0, res.stderr
    assert (tmp_path / "merged.csv").read_text(encoding="utf-8") == (
        "extra,id,name\n,1,a\ne,2,b\n,3,c\n"
    )


# Phrase: "python merge_files.py --output - --key ts,id --desc --schema schema.json
#   --on-type-error coerce-null --memory-limit-mb 128 inputs/*.csv"
# Context: provided schema, composite descending key, bad casts as nulls.
def test_example_schema_desc_composite_key(run, csv_file, tmp_path):
    (tmp_path / "schema.json").write_text(
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
        encoding="utf-8",
    )
    csv_file(
        "inputs/a.csv",
        "id,ts,amount,note,is_active\n"
        "1,2024-07-01T12:00:00Z,1.5,first,true\n"
        "2,2024-07-01T12:00:00+00:00,bad,second,0\n",
    )
    csv_file("inputs/b.csv", "id,ts,note\n3,2024-06-30T23:00:00-01:00,third\n")
    res = run(
        "--output", "-", "--key", "ts,id", "--desc", "--schema", "schema.json",
        "--on-type-error", "coerce-null", "--memory-limit-mb", "128",
        "inputs/a.csv", "inputs/b.csv",
    )
    assert res.returncode == 0, res.stderr
    assert table(res.stdout) == [
        ["id", "ts", "amount", "note", "is_active"],
        ["2", "2024-07-01T12:00:00Z", "", "second", "false"],
        ["1", "2024-07-01T12:00:00Z", "1.5", "first", "true"],
        ["3", "2024-07-01T00:00:00Z", "", "third", ""],
    ]


# Phrase: "python merge_files.py --output merged.csv --key ts,id --schema-strategy consensus
#   inputs/users.csv inputs/events.jsonl.gz inputs/metrics.parquet"
# Context: mixed CSV + JSONL + Parquet, schema inferred by consensus, composite key.
def test_example_mixed_formats_by_consensus(run, tmp_path, csv_file, gz_file, parquet_file):
    import pyarrow as pa

    csv_file("inputs/users.csv", "ts,id,label\n2024-07-01T09:00:00Z,2,u2\n")
    gz_file("inputs/events.jsonl.gz",
            '{"ts": "2024-07-01T09:00:00Z", "id": 1, "label": "e1"}\n'
            '{"ts": "2024-07-01T08:00:00Z", "id": 5, "label": "e5"}\n')
    parquet_file("inputs/metrics.parquet", {
        "ts": (["2024-07-01T10:00:00Z"], pa.string()),
        "id": ([3], pa.int64()),
        "label": (["m3"], pa.string()),
    })
    res = run("--output", "merged.csv", "--key", "ts,id",
              "--schema-strategy", "consensus",
              "inputs/users.csv", "inputs/events.jsonl.gz", "inputs/metrics.parquet")
    assert res.returncode == 0, res.stderr
    assert (tmp_path / "merged.csv").read_text(encoding="utf-8") == (
        "id,label,ts\n"
        "5,e5,2024-07-01T08:00:00Z\n"
        "1,e1,2024-07-01T09:00:00Z\n"
        "2,u2,2024-07-01T09:00:00Z\n"
        "3,m3,2024-07-01T10:00:00Z\n"
    )


# Phrase: "python merge_files.py --output - --key created_at,id --desc --schema schema.json
#   --input-format tsv --compression gzip data/*.tsv.gz"
# Context: authoritative provided schema, TSV source, gzip forced, descending sort.
def test_example_tsv_gzip_provided_schema_desc(run, tmp_path, gz_file):
    (tmp_path / "schema.json").write_text(
        json.dumps({"columns": [{"name": "created_at", "type": "timestamp"},
                                {"name": "id", "type": "int"},
                                {"name": "note", "type": "string"}]}),
        encoding="utf-8",
    )
    gz_file("data/a.tsv.gz", "created_at\tid\tnote\n"
                             "2024-07-01T12:00:00Z\t2\tsecond\n"
                             "2024-07-01T12:00:00Z\t1\tfirst\n")
    gz_file("data/b.tsv.gz", "created_at\tid\tnote\textra\n"
                             "2024-08-01T00:00:00Z\t9\tlater\tdropped\n")
    res = run("--output", "-", "--key", "created_at,id", "--desc",
              "--schema", "schema.json", "--input-format", "tsv",
              "--compression", "gzip", "data/a.tsv.gz", "data/b.tsv.gz")
    assert res.returncode == 0, res.stderr
    assert table(res.stdout) == [
        ["created_at", "id", "note"],
        ["2024-08-01T00:00:00Z", "9", "later"],
        ["2024-07-01T12:00:00Z", "2", "second"],
        ["2024-07-01T12:00:00Z", "1", "first"],
    ]
