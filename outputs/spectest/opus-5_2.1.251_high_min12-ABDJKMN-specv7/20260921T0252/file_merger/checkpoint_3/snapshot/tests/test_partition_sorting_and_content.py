"""Spec sections: Sorting Guarantees, CSV Output Contents, Memory & External
Merge, Determinism Checklist, Examples."""
import os

from conftest import (run_tool, write_csv, write_tsv, write_gz, write_jsonl,
                      write_jsonl_gz, write_schema, read_rows, read_text,
                      part_files, tree_files, tree_dirs, concat_body, concat_col,
                      col,
                      needs_parquet, write_parquet)


# ---------------------------------------------------------------- Sorting
# Phrase: "With no field partitioning: rows must be globally sorted by --key"
# Context: sharded output read in part order is globally ordered.
def test_global_sort_across_shards(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id"] + [str(i) for i in (9, 3, 6)])
    b = write_csv(tmp_path / "b.csv", ["id"] + [str(i) for i in (1, 8, 4)])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id",
                   "--max-rows-per-file", "2", a, b)
    assert res.returncode == 0, res.stderr
    ids = [int(r[0]) for r in concat_body(out)]
    assert ids == sorted(ids)


# Phrase: "(and --desc if set)"
# Context: descending global order across shards.
def test_global_sort_descending_across_shards(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id", "1", "3", "2", "5", "4"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id", "--desc",
                   "--max-rows-per-file", "2", src)
    assert res.returncode == 0, res.stderr
    assert [r[0] for r in concat_body(out)] == ["5", "4", "3", "2", "1"]


# Phrase: "With field partitioning: rows in each partition directory must be
#          sorted by --key within that partition"
# Context: each partition is independently ordered.
def test_rows_sorted_within_each_partition(tmp_path):
    rows = ["id,c"]
    for i in (5, 2, 9, 1, 7, 3):
        rows.append("%d,%s" % (i, "us" if i % 2 else "de"))
    src = write_csv(tmp_path / "a.csv", rows)
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id", "--partition-by", "c", src)
    assert res.returncode == 0, res.stderr
    for name in tree_dirs(out):
        ids = [int(v) for v in concat_col(out / name, "id")]
        assert ids == sorted(ids), name


# Phrase: "rows in each partition directory must be sorted by --key within
#          that partition"
# Context: ordering also holds across part files inside one partition.
def test_partition_order_spans_part_files(tmp_path):
    lines = ["id,c"] + ["%d,us" % i for i in (7, 1, 5, 3, 9)]
    src = write_csv(tmp_path / "a.csv", lines)
    out = tmp_path / "out"
    run_tool("--output", out, "--key", "id", "--partition-by", "c",
             "--max-rows-per-file", "2", src)
    assert concat_col(out / "c=us", "id") == ["1", "3", "5", "7", "9"]


# Phrase: "rows in each partition ... sorted by --key" + "--desc"
# Context: descending order inside partitions.
def test_partition_order_descending(tmp_path):
    lines = ["id,c"] + ["%d,us" % i for i in (2, 4, 1, 3)]
    src = write_csv(tmp_path / "a.csv", lines)
    out = tmp_path / "out"
    run_tool("--output", out, "--key", "id", "--desc",
             "--partition-by", "c", src)
    assert concat_col(out / "c=us", "id") == ["4", "3", "2", "1"]


# Phrase: "rows must be globally sorted by --key"
# Context: multiple key columns order lexicographically, left to right.
def test_multi_key_sort_in_shards(tmp_path):
    src = write_csv(tmp_path / "a.csv",
                    ["u,ts", "b,2", "a,2", "b,1", "a,1"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "u,ts",
                   "--max-rows-per-file", "3", src)
    assert res.returncode == 0, res.stderr
    assert list(zip(concat_col(out, "u"), concat_col(out, "ts"))) == [
        ("a", "1"), ("a", "2"), ("b", "1"), ("b", "2")]


# ------------------------------------------------- CSV output contents
# Phrase: "Every output CSV includes header row in resolved schema column
#          order"
# Context: inferred schema, header repeated in every shard.
def test_header_in_every_output_csv(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["z,a", "1,2", "3,4"])
    out = tmp_path / "out"
    run_tool("--output", out, "--key", "z", "--max-rows-per-file", "1", src)
    for name in part_files(out):
        assert read_rows(out / name)[0] == ["a", "z"]


# Phrase: "Use same delimiter/quote/escape/line-ending/null-literal rules as
#          before"
# Context: comma delimiter, doubled quotes and \n endings in part files.
def test_part_files_use_output_dialect(tmp_path):
    src = write_csv(tmp_path / "a.csv", ['id,v', '7,"a,""b"""'])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id",
                   "--max-rows-per-file", "5", src)
    assert res.returncode == 0, res.stderr
    assert read_text(out / "part-00000.csv") == 'id,v\n7,"a,""b"""\n'


# Phrase: "Use same ... null-literal rules as before"
# Context: --csv-null-literal is honoured in the cells of part files.
def test_null_literal_in_part_files(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,v", "1,", "2,x"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id",
                   "--csv-null-literal", "NULL",
                   "--max-rows-per-file", "5", src)
    assert res.returncode == 0, res.stderr
    assert read_text(out / "part-00000.csv") == "id,v\n1,NULL\n2,x\n"


# Phrase: "Each partition file is independently valid CSV"
# Context: a file can be parsed standalone and its header matches its rows.
def test_each_file_independently_parsable(tmp_path):
    lines = ["id,v"] + ['%d,"quoted,%d"' % (i, i) for i in range(6)]
    src = write_csv(tmp_path / "a.csv", lines)
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id",
                   "--max-rows-per-file", "2", src)
    assert res.returncode == 0, res.stderr
    for name in part_files(out):
        rows = read_rows(out / name)
        assert rows[0] == ["id", "v"]
        assert all(len(r) == 2 for r in rows[1:])


# Phrase: "Each partition file is independently valid CSV"
# Context: every file ends with a line terminator.
def test_files_end_with_newline(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id", "1", "2", "3"])
    out = tmp_path / "out"
    run_tool("--output", out, "--key", "id", "--max-rows-per-file", "2", src)
    for name in part_files(out):
        assert read_text(out / name).endswith("\n")


# ------------------------------------------------- Memory & external merge
# Phrase: "Continue to honor small --memory-limit-mb values"
# Context: a tiny memory limit still produces the full sorted, sharded output.
def test_small_memory_limit_still_correct(tmp_path):
    n = 400
    lines = ["id,c"] + ["%d,%s" % (i, "abcd"[i % 4]) for i in range(n)]
    src = write_csv(tmp_path / "a.csv", lines)
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id", "--memory-limit-mb", "1",
                   "--partition-by", "c", "--max-rows-per-file", "17", src)
    assert res.returncode == 0, res.stderr
    total = 0
    for name in tree_dirs(out):
        ids = [int(v) for v in concat_col(out / name, "id")]
        assert ids == sorted(ids)
        total += len(ids)
    assert total == n


# Phrase: "Tool must work on arbitrarily large inputs"
# Context: external merge and partitioned writing compose; no temp leftovers.
def test_external_merge_leaves_no_temp_dir(tmp_path):
    lines = ["id"] + [str(i) for i in range(500, 0, -1)]
    src = write_csv(tmp_path / "a.csv", lines)
    out = tmp_path / "out"
    tmpd = tmp_path / "scratch"
    res = run_tool("--output", out, "--key", "id", "--memory-limit-mb", "1",
                   "--temp-dir", tmpd, "--max-rows-per-file", "64", src)
    assert res.returncode == 0, res.stderr
    assert list(tmpd.iterdir()) == []


# ------------------------------------------------------------- Examples
# Phrase: "Field-partitioned by country,dt with per-partition sharding to
#          <= 50 MB parts"
# Context: the first worked example, scaled down.
def test_example_country_dt_sharded(tmp_path):
    lines = ["ts,id,country,dt"]
    for i in range(8):
        lines.append("%d,%d,%s,2024-01-0%d"
                     % (100 - i, i, "us" if i % 2 else "de", 1 + i % 2))
    src = write_csv(tmp_path / "a.csv", lines)
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "ts,id",
                   "--partition-by", "country,dt",
                   "--max-bytes-per-file", "40", src)
    assert res.returncode == 0, res.stderr
    assert all(p.startswith("country=") for p in tree_files(out))
    for name in part_files(out / "country=us" / "dt=2024-01-01"):
        assert os.path.getsize(
            str(out / "country=us" / "dt=2024-01-01" / name)) <= 40


# Phrase: "Globally sorted stream sharded into files of <= 1,000,000 rows (no
#          field partitions)"
# Context: the second worked example mixes csv, gzipped jsonl and parquet.
@needs_parquet
def test_example_mixed_inputs_row_sharded(tmp_path):
    a = write_csv(tmp_path / "users.csv", ["user_id,ts", "3,1", "1,9"])
    b = write_jsonl_gz(tmp_path / "events.jsonl.gz",
                       [{"user_id": 2, "ts": 5}, {"user_id": 1, "ts": 2}])
    c = write_parquet(tmp_path / "metrics.parquet",
                      {"user_id": [4, 2], "ts": [7, 1]})
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "user_id,ts",
                   "--max-rows-per-file", "2", a, b, c)
    assert res.returncode == 0, res.stderr
    got = [(int(u), int(t)) for u, t in zip(concat_col(out, "user_id"),
                                            concat_col(out, "ts"))]
    assert got == sorted(got)
    assert len(got) == 6
    assert part_files(out) == ["part-00000.csv", "part-00001.csv",
                               "part-00002.csv"]


# Phrase: "Field-partition only (one file per partition), descending order"
# Context: the third worked example over gzipped TSV inputs.
def test_example_field_partition_only_desc(tmp_path):
    text = "\n".join(["created_at\tid\taccount_id",
                      "2024-01-01\t1\tA",
                      "2024-01-03\t2\tA",
                      "2024-01-02\t3\tB"]) + "\n"
    src = write_gz(tmp_path / "in.tsv.gz", text)
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "created_at,id", "--desc",
                   "--partition-by", "account_id", src)
    assert res.returncode == 0, res.stderr
    assert tree_files(out) == ["account_id=A/part-00000.csv",
                               "account_id=B/part-00000.csv"]
    assert col(read_rows(out / "account_id=A" / "part-00000.csv"),
               "id") == ["2", "1"]


# --------------------------------------------- Determinism checklist
# Phrase: "Directory layout and file names follow exact rules"
# Context: running twice over the same input yields the identical tree.
def test_repeated_runs_identical_tree(tmp_path):
    lines = ["id,c"] + ["%d,%s" % (i, "xy"[i % 2]) for i in range(10)]
    src = write_csv(tmp_path / "a.csv", lines)
    first = tmp_path / "one"
    second = tmp_path / "two"
    run_tool("--output", first, "--key", "id", "--partition-by", "c",
             "--max-rows-per-file", "3", src)
    run_tool("--output", second, "--key", "id", "--partition-by", "c",
             "--max-rows-per-file", "3", src)
    assert tree_files(first) == tree_files(second)
    for name in tree_files(first):
        assert read_text(first / name) == read_text(second / name)


# Phrase: "Directory layout and file names follow exact rules"
# Context: input order does not change the layout for equal keys.
def test_input_order_does_not_change_layout(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id,c", "1,x", "3,y"])
    b = write_csv(tmp_path / "b.csv", ["id,c", "2,y", "4,x"])
    one = tmp_path / "one"
    two = tmp_path / "two"
    run_tool("--output", one, "--key", "id", "--partition-by", "c", a, b)
    run_tool("--output", two, "--key", "id", "--partition-by", "c", b, a)
    assert tree_files(one) == tree_files(two)
    for name in tree_files(one):
        assert read_text(one / name) == read_text(two / name)
