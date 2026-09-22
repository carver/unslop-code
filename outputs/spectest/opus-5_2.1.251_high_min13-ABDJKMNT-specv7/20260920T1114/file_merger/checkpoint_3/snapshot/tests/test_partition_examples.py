"""Spec section: Examples — the three documented partitioned invocations."""

from conftest import read, rows_of, tree


# Phrase: "--output out/ --key ts,id --partition-by country,dt
#          --max-bytes-per-file 52428800 inputs/*.csv"
# Context: Examples. Field partitions with per-partition size sharding.
def test_example_field_partitions_with_byte_sharding(csv_file, run_tool, workdir):
    csv_file(
        "inputs/a.csv",
        "ts,id,country,dt\n"
        "2024-01-01T10:00:00Z,2,US,2024-01-01\n"
        "2024-01-01T09:00:00Z,1,US,2024-01-01\n",
    )
    csv_file(
        "inputs/b.csv",
        "ts,id,country,dt\n2024-01-02T09:00:00Z,3,FR,2024-01-02\n",
    )
    result = run_tool(
        "--output", "out/", "--key", "ts,id",
        "--partition-by", "country,dt",
        "--max-bytes-per-file", "52428800",
        "inputs/a.csv", "inputs/b.csv",
    )
    assert result.returncode == 0, result.stderr
    assert tree(workdir / "out") == [
        "country=FR/dt=2024-01-02/part-00000.csv",
        "country=US/dt=2024-01-01/part-00000.csv",
    ]
    rows = rows_of(read(workdir / "out/country=US/dt=2024-01-01/part-00000.csv"))
    assert [row[2] for row in rows] == ["1", "2"]


# Phrase: "--output out/ --key user_id,ts --max-rows-per-file 1000000
#          inputs/users.csv inputs/events.jsonl.gz inputs/metrics.parquet"
# Context: Examples. A sharded global stream from three input formats.
def test_example_row_sharding_across_formats(
    csv_file, jsonl_file, parquet_file, gzipped, run_tool, workdir
):
    csv_file("inputs/users.csv", "user_id,ts\n3,2024-01-03T00:00:00Z\n")
    gzipped(
        jsonl_file("inputs/events.jsonl", [{"user_id": 1, "ts": "2024-01-01T00:00:00Z"}])
    )
    parquet_file(
        "inputs/metrics.parquet", {"user_id": [2], "ts": ["2024-01-02T00:00:00Z"]}
    )
    result = run_tool(
        "--output", "out/", "--key", "user_id,ts",
        "--max-rows-per-file", "2",
        "inputs/users.csv", "inputs/events.jsonl.gz", "inputs/metrics.parquet",
    )
    assert result.returncode == 0, result.stderr
    assert tree(workdir / "out") == ["part-00000.csv", "part-00001.csv"]
    assert rows_of(read(workdir / "out/part-00000.csv")) == [
        ["2024-01-01T00:00:00Z", "1"],
        ["2024-01-02T00:00:00Z", "2"],
    ]
    assert rows_of(read(workdir / "out/part-00001.csv")) == [
        ["2024-01-03T00:00:00Z", "3"],
    ]


# Phrase: "--output out/ --key created_at,id --desc --partition-by account_id
#          inputs/*.tsv.gz"
# Context: Examples. Field partitions only: one file per partition, descending.
def test_example_field_partition_only_descending(tsv_file, gzipped, run_tool, workdir):
    gzipped(
        tsv_file(
            "inputs/a.tsv",
            "id\tcreated_at\taccount_id\n"
            "1\t2024-01-01T00:00:00Z\t7\n"
            "2\t2024-01-02T00:00:00Z\t7\n"
            "3\t2024-01-03T00:00:00Z\t9\n",
        )
    )
    result = run_tool(
        "--output", "out/", "--key", "created_at,id", "--desc",
        "--partition-by", "account_id", "inputs/a.tsv.gz",
    )
    assert result.returncode == 0, result.stderr
    assert tree(workdir / "out") == [
        "account_id=7/part-00000.csv",
        "account_id=9/part-00000.csv",
    ]
    rows = rows_of(read(workdir / "out/account_id=7/part-00000.csv"))
    assert [row[2] for row in rows] == ["2", "1"]
