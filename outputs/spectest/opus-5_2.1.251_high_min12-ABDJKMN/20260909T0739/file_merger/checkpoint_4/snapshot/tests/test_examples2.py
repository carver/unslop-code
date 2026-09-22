"""The two worked `Examples` of the multi-format checkpoint."""
from conftest import (run, write, write_gz, write_jsonl_gz, write_parquet,
                      write_schema)


# --- Spec: "Mixed CSV + JSONL + Parquet, schema inferred by consensus, sort
#     by composite key:
#     python merge_files.py --output merged.csv --key ts,id
#             --schema-strategy consensus
#             inputs/users.csv inputs/events.jsonl.gz inputs/metrics.parquet"
def test_example_one_mixed_consensus(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    write(inputs, "users.csv", "ts,id,who\n2024-01-02,2,u2\n2024-01-01,1,u1\n")
    write_jsonl_gz(inputs, "events.jsonl.gz",
                   [{"ts": "2024-01-01", "id": 3, "ev": "click"}])
    write_parquet(inputs, "metrics.parquet",
                  [{"ts": "2024-01-03", "id": 4, "m": "cpu"}])
    out = tmp_path / "merged.csv"
    r = run("--output", str(out), "--key", "ts,id",
            "--schema-strategy", "consensus",
            str(inputs / "users.csv"),
            str(inputs / "events.jsonl.gz"),
            str(inputs / "metrics.parquet"),
            cwd=tmp_path)
    assert r.ok, r
    text = out.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0] == "ev,id,m,ts,who"
    assert [line.split(",")[1] for line in lines[1:]] == ["1", "3", "2", "4"]


# --- Spec: "Authoritative provided schema, TSV source, gzip forced,
#     descending sort:
#     python merge_files.py --output - --key created_at,id --desc
#             --schema schema.json --input-format tsv --compression gzip
#             data/*.tsv.gz" ------------------------------------------------
def test_example_two_tsv_gzip_schema_desc(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    schema = write_schema(tmp_path, "schema.json",
                          [("created_at", "timestamp"), ("id", "int"),
                           ("note", "string")])
    write_gz(data, "a.tsv.gz",
             "created_at\tid\tnote\n2024-01-01T00:00:00Z\t1\tfirst\n")
    write_gz(data, "b.tsv.gz",
             "created_at\tid\tnote\n2024-01-02T00:00:00Z\t2\tsecond\n")
    r = run("--output", "-", "--key", "created_at,id", "--desc",
            "--schema", str(schema),
            "--input-format", "tsv", "--compression", "gzip",
            str(data / "a.tsv.gz"), str(data / "b.tsv.gz"),
            cwd=tmp_path)
    assert r.ok, r
    assert r.stdout == (
        "created_at,id,note\n"
        "2024-01-02T00:00:00Z,2,second\n"
        "2024-01-01T00:00:00Z,1,first\n"
    )
