"""Checkpoint 3: cutting the output stream into `part-xxxxx.csv` shards."""


def _numbered(csv_file, name, count, tag="a"):
    """A CSV of `count` rows whose ids count up from 1, one character per tag."""
    body = "".join(f"{index},{tag}\n" for index in range(1, count + 1))
    return csv_file(name, "id,tag\n" + body)


def _rows_of(path):
    return path.read_text(encoding="utf-8").splitlines()[1:]


def test_max_rows_per_file_caps_data_rows(run_cli, csv_file, tmp_path, tree):
    # Spec: "--max-rows-per-file <INT>: cut output into files with at most INT data
    # rows each (header not counted)"
    a = _numbered(csv_file, "a.csv", 5)
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--max-rows-per-file", "2", a)
    assert tree(out) == ["part-00000.csv", "part-00001.csv", "part-00002.csv"]
    assert [len(_rows_of(out / name)) for name in tree(out)] == [2, 2, 1]


def test_max_rows_boundary_leaves_no_empty_trailing_file(run_cli, csv_file, tmp_path, tree):
    # Spec: "files with at most INT data rows each"
    a = _numbered(csv_file, "a.csv", 4)
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--max-rows-per-file", "2", a)
    assert tree(out) == ["part-00000.csv", "part-00001.csv"]


def test_shards_are_named_in_the_order_rows_are_emitted(run_cli, csv_file, tmp_path):
    # Spec: "write files directly under --output as part-00000.csv, part-00001.csv, …
    # in exact order rows are emitted from sorted stream"
    a = csv_file("a.csv", "id,tag\n3,c\n1,a\n4,d\n2,b\n")
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--max-rows-per-file", "2", a)
    assert _rows_of(out / "part-00000.csv") == ["1,a", "2,b"]
    assert _rows_of(out / "part-00001.csv") == ["3,c", "4,d"]


def test_shard_names_are_zero_padded_to_width_five(run_cli, csv_file, tmp_path, tree):
    # Spec: "`part-00000.csv`, `part-00001.csv`, … (zero-padded width 5)"
    a = _numbered(csv_file, "a.csv", 12)
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--max-rows-per-file", "1", a)
    assert tree(out)[:3] == ["part-00000.csv", "part-00001.csv", "part-00002.csv"]
    assert tree(out)[-1] == "part-00011.csv"


def test_every_shard_repeats_the_header(run_cli, csv_file, tmp_path, tree):
    # Spec: "Each file contains header row (resolved schema header)"
    a = _numbered(csv_file, "a.csv", 3)
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--max-rows-per-file", "1", a)
    headers = [(out / name).read_text(encoding="utf-8").splitlines()[0] for name in tree(out)]
    assert headers == ["id,tag"] * 3


def test_max_bytes_per_file_bounds_the_on_disk_size(run_cli, csv_file, tmp_path, tree):
    # Spec: "--max-bytes-per-file <INT>: cut so on-disk byte size of each file
    # (including header and line endings) is ≤ INT"
    a = _numbered(csv_file, "a.csv", 5)
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--max-bytes-per-file", "15", a)
    # header "id,tag\n" is 7 bytes and each row "N,a\n" is 4, so two rows fit exactly
    assert [len(_rows_of(out / name)) for name in tree(out)] == [2, 2, 1]
    assert all((out / name).stat().st_size <= 15 for name in tree(out))


def test_max_bytes_counts_the_header(run_cli, csv_file, tmp_path, tree):
    # Spec: "byte size of each file (including header and line endings)"
    a = _numbered(csv_file, "a.csv", 4)
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--max-bytes-per-file", "11", a)
    # 7 header bytes leave room for exactly one 4-byte row
    assert [len(_rows_of(out / name)) for name in tree(out)] == [1, 1, 1, 1]


def test_oversized_row_is_written_alone(run_cli, csv_file, tmp_path, tree):
    # Spec: "Exception: if single row alone exceeds INT, place that row in file by
    # itself (allowed to exceed limit)"
    a = _numbered(csv_file, "a.csv", 2, tag="z" * 30)
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--max-bytes-per-file", "20", a)
    assert tree(out) == ["part-00000.csv", "part-00001.csv"]
    assert [len(_rows_of(out / name)) for name in tree(out)] == [1, 1]
    assert (out / "part-00000.csv").stat().st_size == 40


def test_oversized_row_does_not_absorb_the_next_row(run_cli, csv_file, tmp_path, tree):
    # Spec: "place that row in file by itself"
    a = csv_file("a.csv", "id,tag\n1," + "z" * 30 + "\n2,b\n")
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--max-bytes-per-file", "20", a)
    assert _rows_of(out / "part-00000.csv") == ["1," + "z" * 30]
    assert _rows_of(out / "part-00001.csv") == ["2,b"]


def test_both_limits_cut_at_the_earliest_boundary(run_cli, csv_file, tmp_path, tree):
    # Spec: "When both --max-rows-per-file and --max-bytes-per-file provided, cut at
    # earliest boundary that would violate either constraint"
    a = _numbered(csv_file, "a.csv", 6)
    out = tmp_path / "out"
    run_cli(
        "--output", out, "--key", "id",
        "--max-rows-per-file", "5", "--max-bytes-per-file", "15", a,
    )
    assert [len(_rows_of(out / name)) for name in tree(out)] == [2, 2, 2]


def test_both_limits_honour_the_row_count_when_it_binds_first(run_cli, csv_file, tmp_path, tree):
    # Spec: "cut at earliest boundary that would violate either constraint"
    a = _numbered(csv_file, "a.csv", 4)
    out = tmp_path / "out"
    run_cli(
        "--output", out, "--key", "id",
        "--max-rows-per-file", "1", "--max-bytes-per-file", "1000", a,
    )
    assert [len(_rows_of(out / name)) for name in tree(out)] == [1, 1, 1, 1]


def test_sharding_restarts_the_sequence_inside_each_partition(run_cli, csv_file, tmp_path, tree):
    # Spec: "File naming (with field partitioning): same part-xxxxx.csv sequence per
    # partition directory"
    body = "".join(f"{index},{'xy'[index % 2]}\n" for index in range(6))
    a = csv_file("a.csv", "id,g\n" + body)
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--partition-by", "g", "--max-rows-per-file", "2", a)
    assert tree(out) == [
        "g=x/part-00000.csv",
        "g=x/part-00001.csv",
        "g=y/part-00000.csv",
        "g=y/part-00001.csv",
    ]
    assert _rows_of(out / "g=x" / "part-00000.csv") == ["x,0", "x,2"]
    assert _rows_of(out / "g=y" / "part-00001.csv") == ["y,5"]


def test_sharded_stream_keeps_every_row_exactly_once(run_cli, csv_file, tmp_path, tree):
    # Spec: shards together are the sorted stream — "in exact order rows are emitted"
    a = _numbered(csv_file, "a.csv", 25)
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--max-rows-per-file", "4", a)
    emitted = [row for name in tree(out) for row in _rows_of(out / name)]
    assert emitted == [f"{index},a" for index in range(1, 26)]


def test_empty_input_still_writes_one_header_only_shard(run_cli, csv_file, tmp_path, tree):
    # Spec: "write files directly under --output as part-00000.csv" (AMBIGUITIES T37)
    a = csv_file("a.csv", "id,tag\n")
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--max-rows-per-file", "10", a)
    assert tree(out) == ["part-00000.csv"]
    assert (out / "part-00000.csv").read_text(encoding="utf-8") == "id,tag\n"
