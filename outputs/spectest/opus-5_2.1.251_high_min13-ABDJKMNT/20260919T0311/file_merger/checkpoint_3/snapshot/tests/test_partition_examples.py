"""Spec sections: Examples and the Determinism Checklist."""
from conftest import data_rows, parts, tree


# Phrase: "--output out/ --key ts,id --partition-by country,dt
#   --max-bytes-per-file 52428800 inputs/*.csv"
# Context: field partitioning plus per-partition byte sharding, with a trailing
#   slash on --output.
def test_example_field_partitioned_with_byte_shards(run, csv_file, tmp_path):
    csv_file("inputs/a.csv", "ts,id,country,dt\n"
             "2024-01-01T00:00:00Z,2,US,2024-01-01\n"
             "2024-01-01T00:00:00Z,1,US,2024-01-01\n"
             "2024-01-02T00:00:00Z,3,FR,2024-01-02\n")
    res = run("--output", "out/", "--key", "ts,id",
              "--partition-by", "country,dt", "--max-bytes-per-file", "52428800",
              "inputs/a.csv")
    assert res.returncode == 0, res.stderr
    assert tree(tmp_path / "out") == [
        "country=FR/dt=2024-01-02/part-00000.csv",
        "country=US/dt=2024-01-01/part-00000.csv",
    ]
    rows = data_rows(tmp_path / "out" / "country=US" / "dt=2024-01-01" / "part-00000.csv")
    assert [r[2] for r in rows] == ["1", "2"]


# Phrase: "--key user_id,ts --max-rows-per-file 1000000 inputs/users.csv
#   inputs/events.jsonl.gz inputs/metrics.parquet"
# Context: a globally sorted stream sharded by row count, across mixed formats.
def test_example_row_sharded_across_formats(run, csv_file, gz_file, parquet_file, tmp_path):
    import pyarrow as pa

    csv_file("inputs/users.csv", "user_id,ts\n3,2024-01-03T00:00:00Z\n")
    gz_file("inputs/events.jsonl.gz", '{"user_id": 1, "ts": "2024-01-01T00:00:00Z"}\n')
    parquet_file("inputs/metrics.parquet",
                 {"user_id": ([2], pa.int64()), "ts": (["2024-01-02T00:00:00Z"], pa.string())})
    res = run("--output", "out", "--key", "user_id,ts", "--max-rows-per-file", "2",
              "inputs/users.csv", "inputs/events.jsonl.gz", "inputs/metrics.parquet")
    assert res.returncode == 0, res.stderr
    assert tree(tmp_path / "out") == ["part-00000.csv", "part-00001.csv"]
    assert [r[1] for p in parts(tmp_path / "out") for r in data_rows(p)] == ["1", "2", "3"]


# Phrase: "--key created_at,id --desc --partition-by account_id inputs/*.tsv.gz"
# Context: field partitioning only, descending, one file per partition.
def test_example_field_partition_only_descending(run, gz_file, tmp_path):
    gz_file("inputs/a.tsv.gz", "account_id\tcreated_at\tid\n"
            "7\t2024-01-01\t1\n7\t2024-01-03\t2\n8\t2024-01-02\t3\n")
    res = run("--output", "out", "--key", "created_at,id", "--desc",
              "--partition-by", "account_id", "inputs/a.tsv.gz")
    assert res.returncode == 0, res.stderr
    assert tree(tmp_path / "out") == [
        "account_id=7/part-00000.csv", "account_id=8/part-00000.csv",
    ]
    assert [r[1] for r in data_rows(tmp_path / "out" / "account_id=7" / "part-00000.csv")] == \
        ["2024-01-03", "2024-01-01"]


# Phrase: "Directory layout and file names follow exact rules"
# Context: two identical runs produce byte-identical trees.
def test_two_runs_produce_identical_trees(run, csv_file, tmp_path):
    csv_file("a.csv", "id,c\n3,US\n1,FR\n2,US\n")
    for name in ("out1", "out2"):
        assert run("--output", name, "--key", "id", "--partition-by", "c",
                   "--max-rows-per-file", "1", "a.csv").returncode == 0
    assert tree(tmp_path / "out1") == tree(tmp_path / "out2")
    for relative in tree(tmp_path / "out1"):
        assert (tmp_path / "out1" / relative).read_bytes() == \
            (tmp_path / "out2" / relative).read_bytes()


# Phrase: "Exact exit codes and stderr message shapes as specified"
# Context: a successful partitioned run says nothing on either stream.
def test_successful_run_is_silent(run, csv_file):
    csv_file("a.csv", "id,c\n1,US\n")
    res = run("--output", "out", "--key", "id", "--partition-by", "c", "a.csv")
    assert (res.returncode, res.stdout, res.stderr) == (0, "", "")


# Phrase: "Exact exit codes and stderr message shapes as specified"
# Context: a cast failure inside a partitioned run keeps its own exit code.
def test_cast_failure_keeps_its_exit_code(run, csv_file, schema_file):
    csv_file("a.csv", "id,c\nnope,US\n")
    schema = schema_file([("id", "int"), ("c", "string")])
    res = run("--output", "out", "--key", "id", "--partition-by", "c",
              "--schema", schema, "--on-type-error", "fail", "a.csv")
    assert res.returncode == 4, res.stderr
    assert res.stderr.startswith("error: ")
