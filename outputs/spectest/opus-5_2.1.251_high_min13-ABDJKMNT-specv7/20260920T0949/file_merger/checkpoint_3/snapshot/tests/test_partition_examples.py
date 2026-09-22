"""The three worked examples from the spec, on small inputs."""

from conftest import rows_of


# Spec: "Field-partitioned by `country,dt` with per-partition sharding to <= 50 MB parts"
def test_country_dt_example(make_csv, run, tree, read):
    make_csv("one.csv", "ts,id,country,dt\n2,b,us,2024-01-01\n1,a,us,2024-01-01\n")
    make_csv("two.csv", "ts,id,country,dt\n3,c,fr,2024-01-02\n")
    run(
        "--output", "out", "--key", "ts,id", "--partition-by", "country,dt",
        "--max-bytes-per-file", "52428800", "one.csv", "two.csv",
    )
    assert tree("out") == [
        "country=fr/dt=2024-01-02/part-00000.csv",
        "country=us/dt=2024-01-01/part-00000.csv",
    ]
    assert rows_of(read("out/country=us/dt=2024-01-01/part-00000.csv"))[1:] == [
        ["us", "2024-01-01", "a", "1"],
        ["us", "2024-01-01", "b", "2"],
    ]


# Spec: "Globally sorted stream sharded into files of <= 1,000,000 rows (no
# field partitions)" across csv, jsonl.gz and parquet inputs
def test_mixed_input_sharding_example(make_csv, make_jsonl, make_parquet, gzipped, run, tree, read):
    make_csv("users.csv", "user_id,ts\n3,30\n1,10\n")
    events = make_jsonl("events.jsonl", [{"user_id": 2, "ts": 20}])
    gzipped(events)
    make_parquet("metrics.parquet", {"user_id": [4], "ts": [40]})
    run(
        "--output", "out", "--key", "user_id,ts", "--max-rows-per-file", "3",
        "users.csv", "events.jsonl.gz", "metrics.parquet",
    )
    assert tree("out") == ["part-00000.csv", "part-00001.csv"]
    assert rows_of(read("out/part-00000.csv"))[1:] == [["10", "1"], ["20", "2"], ["30", "3"]]
    assert rows_of(read("out/part-00001.csv"))[1:] == [["40", "4"]]


# Spec: "Field-partition only (one file per partition), descending order"
def test_descending_field_partition_example(make_text, gzipped, run, tree, read):
    source = make_text("a.tsv", "created_at\tid\taccount_id\n2024-01-01\t1\tA\n2024-01-03\t3\tA\n")
    gzipped(source)
    run(
        "--output", "out", "--key", "created_at,id", "--desc",
        "--partition-by", "account_id", "a.tsv.gz",
    )
    assert tree("out") == ["account_id=A/part-00000.csv"]
    assert rows_of(read("out/account_id=A/part-00000.csv"))[1:] == [
        ["A", "2024-01-03", "3"],
        ["A", "2024-01-01", "1"],
    ]
