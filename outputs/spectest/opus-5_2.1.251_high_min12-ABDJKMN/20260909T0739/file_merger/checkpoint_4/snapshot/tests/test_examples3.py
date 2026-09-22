"""The worked `Examples` of the partitioned-output checkpoint."""
import os
from pathlib import Path

from conftest import (column, data_rows, read_rows, run, tree, write, write_gz,
                      write_parquet)


# --- Spec: "Field-partitioned by `country,dt` with per-partition sharding to
#     ≤ 50 MB parts:
#     python merge_files.py --output out/ --key ts,id
#             --partition-by country,dt --max-bytes-per-file 52428800
#             inputs/*.csv" --------------------------------------------------
def test_example_one_country_dt_partitions(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    write(inputs, "a.csv",
          "ts,id,country,dt\n"
          "2024-01-02T00:00:00Z,2,US,2024-01-02\n"
          "2024-01-01T00:00:00Z,1,US,2024-01-01\n")
    write(inputs, "b.csv",
          "ts,id,country,dt\n"
          "2024-01-01T05:00:00Z,3,DE,2024-01-01\n")
    out = tmp_path / "out"
    r = run("--output", str(out) + "/", "--key", "ts,id",
            "--partition-by", "country,dt",
            "--max-bytes-per-file", "52428800",
            str(inputs / "a.csv"), str(inputs / "b.csv"), cwd=tmp_path)
    assert r.ok, r
    assert tree(out) == [
        "country=DE/dt=2024-01-01/part-00000.csv",
        "country=US/dt=2024-01-01/part-00000.csv",
        "country=US/dt=2024-01-02/part-00000.csv",
    ]
    rows = read_rows(out / "country=US" / "dt=2024-01-01" / "part-00000.csv")
    assert rows[0] == ["country", "dt", "id", "ts"]
    assert column(out / "country=US" / "dt=2024-01-01" / "part-00000.csv",
                  "id") == ["1"]


# --- Spec: "Globally sorted stream sharded into files of ≤ 1,000,000 rows (no
#     field partitions):
#     python merge_files.py --output out/ --key user_id,ts
#             --max-rows-per-file 1000000
#             inputs/users.csv inputs/events.jsonl.gz inputs/metrics.parquet"
def test_example_two_global_shard(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    write(inputs, "users.csv", "user_id,ts\n2,2024-01-02\n1,2024-01-01\n")
    write_gz(inputs, "events.jsonl.gz",
             '{"user_id": 3, "ts": "2024-01-03"}\n')
    write_parquet(inputs, "metrics.parquet", [{"user_id": 4, "ts": "2024-01-04"}])
    out = tmp_path / "out"
    r = run("--output", str(out) + "/", "--key", "user_id,ts",
            "--max-rows-per-file", "1000000",
            str(inputs / "users.csv"), str(inputs / "events.jsonl.gz"),
            str(inputs / "metrics.parquet"), cwd=tmp_path)
    assert r.ok, r
    assert tree(out) == ["part-00000.csv"]
    assert column(out / "part-00000.csv", "user_id") == ["1", "2", "3", "4"]


# --- Spec: "Field-partition only (one file per partition), descending order:
#     python merge_files.py --output out/ --key created_at,id --desc
#             --partition-by account_id inputs/*.tsv.gz" --------------------
def test_example_three_partition_only_desc(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    write_gz(inputs, "a.tsv.gz",
             "created_at\tid\taccount_id\n"
             "2024-01-01\t1\tacct 1\n"
             "2024-01-03\t3\tacct 1\n"
             "2024-01-02\t2\tacct/2\n")
    out = tmp_path / "out"
    r = run("--output", str(out) + "/", "--key", "created_at,id", "--desc",
            "--partition-by", "account_id", str(inputs / "a.tsv.gz"), cwd=tmp_path)
    assert r.ok, r
    assert tree(out) == [
        "account_id=acct%201/part-00000.csv",
        "account_id=acct%2F2/part-00000.csv",
    ]
    assert column(out / "account_id=acct%201" / "part-00000.csv",
                  "id") == ["3", "1"]
