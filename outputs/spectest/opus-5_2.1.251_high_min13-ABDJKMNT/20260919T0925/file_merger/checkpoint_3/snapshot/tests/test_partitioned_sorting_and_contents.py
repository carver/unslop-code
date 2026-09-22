"""Checkpoint 3: ordering guarantees and CSV contents of partitioned output."""

import csv
import io


def _read(path):
    """Parse one part file as CSV, returning header-first rows."""
    return list(csv.reader(io.StringIO(path.read_text(encoding="utf-8"), newline="")))


def test_sharded_stream_is_globally_sorted(run_cli, csv_file, tmp_path, tree):
    # Spec: "With no field partitioning: rows must be globally sorted by --key"
    a = csv_file("a.csv", "id\n5\n3\n9\n")
    b = csv_file("b.csv", "id\n1\n7\n")
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--max-rows-per-file", "2", a, b)
    emitted = [row[0] for name in tree(out) for row in _read(out / name)[1:]]
    assert emitted == ["1", "3", "5", "7", "9"]


def test_sharded_stream_honours_desc(run_cli, csv_file, tmp_path, tree):
    # Spec: "rows must be globally sorted by --key (and --desc if set)"
    a = csv_file("a.csv", "id\n5\n3\n9\n1\n")
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--desc", "--max-rows-per-file", "2", a)
    emitted = [row[0] for name in tree(out) for row in _read(out / name)[1:]]
    assert emitted == ["9", "5", "3", "1"]


def test_multiple_key_columns_order_the_stream(run_cli, csv_file, tmp_path):
    # Spec example: "--key ts,id"
    a = csv_file("a.csv", "ts,id\n2,b\n1,z\n2,a\n1,a\n")
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "ts,id", "--max-rows-per-file", "10", a)
    assert _read(out / "part-00000.csv")[1:] == [["a", "1"], ["z", "1"], ["a", "2"], ["b", "2"]]


def test_rows_are_sorted_within_each_partition(run_cli, csv_file, tmp_path):
    # Spec: "With field partitioning: rows in each partition directory must be sorted
    # by --key within that partition"
    a = csv_file("a.csv", "id,g\n9,x\n2,y\n4,x\n1,y\n7,x\n")
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--partition-by", "g", a)
    assert [row[1] for row in _read(out / "g=x" / "part-00000.csv")[1:]] == ["4", "7", "9"]
    assert [row[1] for row in _read(out / "g=y" / "part-00000.csv")[1:]] == ["1", "2"]


def test_partitions_are_sorted_descending_when_asked(run_cli, csv_file, tmp_path):
    # Spec example: "--key created_at,id --desc --partition-by account_id"
    a = csv_file("a.csv", "account_id,created_at,id\n7,2024-01-01,b\n7,2024-01-03,a\n7,2024-01-02,c\n")
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "created_at,id", "--desc", "--partition-by", "account_id", a)
    rows = _read(out / "account_id=7" / "part-00000.csv")[1:]
    assert [row[1] for row in rows] == ["2024-01-03", "2024-01-02", "2024-01-01"]


def test_sorting_holds_across_shards_within_a_partition(run_cli, csv_file, tmp_path, tree):
    # Spec: "rows in each partition directory must be sorted by --key within that
    # partition" combined with per-partition sharding
    body = "".join(f"{index},{index % 3}\n" for index in reversed(range(12)))
    a = csv_file("a.csv", "id,g\n" + body)
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--partition-by", "g", "--max-rows-per-file", "2", a)
    emitted = [row[1] for name in tree(out) if name.startswith("g=2/") for row in _read(out / name)[1:]]
    assert emitted == ["2", "5", "8", "11"]


def test_every_part_file_is_independently_valid_csv(run_cli, csv_file, tmp_path, tree):
    # Spec: "Each partition file is independently valid CSV"
    a = csv_file("a.csv", 'id,g,note\n1,x,"a,b"\n2,x,"has ""quotes"""\n3,y,plain\n')
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--partition-by", "g", "--max-rows-per-file", "1", a)
    parsed = {name: _read(out / name) for name in tree(out)}
    assert all(rows[0] == ["g", "id", "note"] for rows in parsed.values())
    assert parsed["g=x/part-00000.csv"][1] == ["x", "1", "a,b"]
    assert parsed["g=x/part-00001.csv"][1] == ["x", "2", 'has "quotes"']


def test_header_is_the_resolved_schema_column_order(run_cli, csv_file, tmp_path):
    # Spec: "Every output CSV includes header row in resolved schema column order"
    schema = tmp_path / "schema.json"
    schema.write_text(
        '{"columns": [{"name": "note", "type": "string"},'
        ' {"name": "id", "type": "int"}, {"name": "g", "type": "string"}]}',
        encoding="utf-8",
    )
    a = csv_file("a.csv", "id,g,note\n1,x,hello\n")
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--schema", schema, "--partition-by", "g", a)
    assert _read(out / "g=x" / "part-00000.csv") == [["note", "id", "g"], ["hello", "1", "x"]]


def test_null_literal_applies_inside_part_files(run_cli, csv_file, tmp_path):
    # Spec: "Use same delimiter/quote/escape/line-ending/null-literal rules as before"
    a = csv_file("a.csv", "id,g,note\n4,x,\n")
    out = tmp_path / "out"
    run_cli(
        "--output", out, "--key", "id", "--partition-by", "g", "--csv-null-literal", "NULL", a
    )
    assert _read(out / "g=x" / "part-00000.csv")[1] == ["x", "4", "NULL"]


def test_quote_character_flag_applies_inside_part_files(run_cli, csv_file, tmp_path):
    # Spec: "Use same delimiter/quote/escape/line-ending/null-literal rules as before"
    a = csv_file("a.csv", "id,g,note\n4,x,'a,b'\n")
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--partition-by", "g", "--csv-quotechar", "'", a)
    assert (out / "g=x" / "part-00000.csv").read_text(encoding="utf-8") == (
        "g,id,note\nx,4,'a,b'\n"
    )


def test_line_endings_are_newlines(run_cli, csv_file, tmp_path):
    # Spec: "Use same delimiter/quote/escape/line-ending ... rules as before"
    a = csv_file("a.csv", "id,g\n1,x\n2,x\n")
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--partition-by", "g", a)
    assert (out / "g=x" / "part-00000.csv").read_bytes() == b"g,id\nx,1\nx,2\n"


def test_partition_columns_stay_in_the_part_files(run_cli, csv_file, tmp_path):
    # Spec: "Every output CSV includes header row in resolved schema column order"
    # — the partition columns are part of that schema (AMBIGUITIES T35)
    a = csv_file("a.csv", "id,g\n4,x\n")
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--partition-by", "g", a)
    assert _read(out / "g=x" / "part-00000.csv") == [["g", "id"], ["x", "4"]]


def test_partitioning_survives_a_tiny_memory_limit(run_cli, csv_file, tmp_path, tree):
    # Spec: "Continue to honor small --memory-limit-mb values" and "Tool must work on
    # arbitrarily large inputs"
    body = "".join(f"{(index * 7919) % 2000},{index % 4},{'p' * 40}\n" for index in range(2000))
    a = csv_file("a.csv", "id,g,pad\n" + body)
    out = tmp_path / "out"
    result = run_cli(
        "--output", out, "--key", "id", "--partition-by", "g",
        "--max-rows-per-file", "97", "--memory-limit-mb", "1", a,
    )
    assert result.returncode == 0, result.stderr
    for group in range(4):
        names = [name for name in tree(out) if name.startswith(f"g={group}/")]
        ids = [int(row[1]) for name in names for row in _read(out / name)[1:]]
        assert ids == sorted(ids)
        assert sum(len(_read(out / name)) - 1 for name in names) == 500


def test_mixed_format_inputs_shard_into_one_sorted_stream(
    run_cli, csv_file, jsonl_file, parquet_file, tmp_path, tree
):
    # Spec example: "--key user_id,ts --max-rows-per-file ... users.csv events.jsonl.gz metrics.parquet"
    users = csv_file("users.csv", "user_id,ts\n3,1\n1,2\n")
    events = jsonl_file("events.jsonl.gz", [{"user_id": 2, "ts": 5}, {"user_id": 4, "ts": 6}])
    metrics = parquet_file("metrics.parquet", {"user_id": [5], "ts": [7]})
    out = tmp_path / "out"
    result = run_cli(
        "--output", out, "--key", "user_id,ts", "--max-rows-per-file", "2", users, events, metrics
    )
    assert result.returncode == 0, result.stderr
    # the inferred header is ts,user_id, so the second cell is the leading sort key
    emitted = [row[1] for name in tree(out) for row in _read(out / name)[1:]]
    assert emitted == ["1", "2", "3", "4", "5"]


def test_field_partitioning_with_byte_limit_example(run_cli, csv_file, tmp_path, tree):
    # Spec example: "--key ts,id --partition-by country,dt --max-bytes-per-file 52428800"
    a = csv_file(
        "a.csv",
        "ts,id,country,dt\n2,b,US,2024-01-01\n1,a,US,2024-01-01\n3,c,FR,2024-01-02\n",
    )
    out = tmp_path / "out"
    result = run_cli(
        "--output", out, "--key", "ts,id", "--partition-by", "country,dt",
        "--max-bytes-per-file", "52428800", a,
    )
    assert result.returncode == 0, result.stderr
    assert tree(out) == [
        "country=FR/dt=2024-01-02/part-00000.csv",
        "country=US/dt=2024-01-01/part-00000.csv",
    ]
    # header is country,dt,id,ts, so the last cell carries the leading sort key
    assert [row[3] for row in _read(out / "country=US" / "dt=2024-01-01" / "part-00000.csv")[1:]] == [
        "1",
        "2",
    ]


def test_nothing_is_written_to_stdout_when_partitioning(run_cli, csv_file, tmp_path):
    # Spec: "When any partitioning flag provided: --output must be directory path"
    a = csv_file("a.csv", "id,g\n1,x\n")
    out = tmp_path / "out"
    result = run_cli("--output", out, "--key", "id", "--partition-by", "g", a)
    assert result.stdout == ""
    assert result.stderr == ""
