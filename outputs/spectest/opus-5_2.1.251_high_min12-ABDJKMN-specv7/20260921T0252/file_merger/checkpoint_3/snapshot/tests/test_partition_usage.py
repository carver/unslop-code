"""Spec section: Partitioned Output -> Usage."""
from conftest import run_tool, write_csv, tree_files, part_files


# Phrase: "[--partition-by <col>[,<col>...]]"
# Context: the flag exists and is optional.
def test_partition_by_flag_exists():
    res = run_tool("--help")
    assert res.returncode == 0
    assert "--partition-by" in res.stdout


# Phrase: "[--max-rows-per-file <INT>] [--max-bytes-per-file <INT>]"
# Context: both sharding flags exist and are optional.
def test_shard_flags_exist():
    res = run_tool("--help")
    assert "--max-rows-per-file" in res.stdout
    assert "--max-bytes-per-file" in res.stdout


# Phrase: the usage block keeps every earlier flag
# Context: the checkpoint-2 flags are still accepted alongside the new ones.
def test_previous_flags_still_present():
    out = run_tool("--help").stdout
    for flag in ("--output", "--key", "--desc", "--schema", "--infer",
                 "--schema-strategy", "--on-type-error", "--memory-limit-mb",
                 "--temp-dir", "--csv-quotechar", "--csv-escapechar",
                 "--csv-null-literal", "--input-format", "--compression",
                 "--parquet-row-group-bytes"):
        assert flag in out, flag


# Phrase: "<INPUT1> [<INPUT2> ...]"
# Context: partitioning works over several inputs at once.
def test_multiple_inputs_with_partitioning(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id,c", "1,x"])
    b = write_csv(tmp_path / "b.csv", ["id,c", "2,y"])
    out = tmp_path / "out"
    res = run_tool("--output", out, "--key", "id",
                   "--partition-by", "c", a, b)
    assert res.returncode == 0, res.stderr
    assert tree_files(out) == ["c=x/part-00000.csv", "c=y/part-00000.csv"]


# Phrase: the full usage line
# Context: all new flags combine with the pre-existing ones in one run.
def test_all_flags_combined(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,c,v", "2,x,1", "1,x,2", "3,y,3"])
    out = tmp_path / "out"
    res = run_tool("--output", out,
                   "--key", "id",
                   "--partition-by", "c",
                   "--max-rows-per-file", "1",
                   "--max-bytes-per-file", "4096",
                   "--desc",
                   "--infer", "strict",
                   "--schema-strategy", "union",
                   "--on-type-error", "coerce-null",
                   "--memory-limit-mb", "8",
                   "--temp-dir", str(tmp_path / "scratch"),
                   "--csv-quotechar", '"',
                   "--csv-escapechar", "\\",
                   "--csv-null-literal", "",
                   "--input-format", "csv",
                   "--compression", "none",
                   "--parquet-row-group-bytes", "1048576",
                   src)
    assert res.returncode == 0, res.stderr
    assert part_files(out / "c=x") == ["part-00000.csv", "part-00001.csv"]
