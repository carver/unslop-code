"""End-to-end tests for partitioned and sharded output directories."""

import csv
import gzip
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from merge_files import main


def write(path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    return str(path)


def run(*args: str) -> None:
    assert main(list(args)) == 0


def read(path: Path) -> list[list[str]]:
    return list(csv.reader(path.read_text(encoding="utf-8").splitlines()))


def parts(directory: Path) -> list[Path]:
    """Part files of one directory, in name order."""
    return sorted(directory.glob("part-*.csv"))


def tree(root: Path) -> list[str]:
    """Every file under ``root`` as a sorted list of relative paths."""
    return sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())


def test_field_partitions_use_hive_segments(tmp_path):
    source = write(
        tmp_path / "a.csv",
        "country,dt,id\nUS,2024-01-01,2\nDE,2024-01-02,3\nUS,2024-01-01,1\n",
    )
    output = tmp_path / "out"
    run("--output", str(output), "--key", "id", "--partition-by", "country,dt", source)
    assert tree(output) == [
        "country=DE/dt=2024-01-02/part-00000.csv",
        "country=US/dt=2024-01-01/part-00000.csv",
    ]
    rows = read(output / "country=US" / "dt=2024-01-01" / "part-00000.csv")
    assert rows[0] == ["country", "dt", "id"]
    assert [row[2] for row in rows[1:]] == ["1", "2"]


def test_partition_values_are_percent_encoded(tmp_path):
    source = write(
        tmp_path / "a.csv",
        'name,id\n"a/b",1\n"new york",2\nnaïve~,3\n,4\n',
    )
    output = tmp_path / "out"
    run("--output", str(output), "--key", "id", "--partition-by", "name", source)
    assert tree(output) == [
        "name=_null/part-00000.csv",
        "name=a%2Fb/part-00000.csv",
        "name=na%C3%AFve%7E/part-00000.csv",
        "name=new%20york/part-00000.csv",
    ]


def test_partition_values_come_from_the_cast_type(tmp_path):
    """``1``/``0`` infer as a bool, so the directories are named after it."""
    source = write(tmp_path / "a.csv", "flag,id\n1,1\n0,2\n")
    output = tmp_path / "out"
    run("--output", str(output), "--key", "id", "--partition-by", "flag", source)
    assert tree(output) == ["flag=false/part-00000.csv", "flag=true/part-00000.csv"]


def test_row_sharding_keeps_the_global_order(tmp_path):
    source = write(tmp_path / "a.csv", "k\n" + "".join(f"{i}\n" for i in reversed(range(10))))
    output = tmp_path / "out"
    run("--output", str(output), "--key", "k", "--max-rows-per-file", "4", source)
    files = parts(output)
    assert [path.name for path in files] == [
        "part-00000.csv",
        "part-00001.csv",
        "part-00002.csv",
    ]
    assert [read(path)[0] for path in files] == [["k"]] * 3
    assert [len(read(path)) - 1 for path in files] == [4, 4, 2]
    assert [row[0] for path in files for row in read(path)[1:]] == [str(i) for i in range(10)]


def test_byte_sharding_respects_the_limit(tmp_path):
    """Three 5-byte rows fit next to the 2-byte header; a fourth would not."""
    source = write(tmp_path / "a.csv", "k\n" + "".join(f"a{i:03d}\n" for i in range(12)))
    output = tmp_path / "out"
    run("--output", str(output), "--key", "k", "--max-bytes-per-file", "20", source)
    files = parts(output)
    assert [path.stat().st_size for path in files] == [17, 17, 17, 17]
    assert [row[0] for path in files for row in read(path)[1:]] == [
        f"a{i:03d}" for i in range(12)
    ]


def test_a_row_larger_than_the_byte_limit_gets_its_own_file(tmp_path):
    source = write(tmp_path / "a.csv", f"k,v\n1,short\n2,{'x' * 100}\n3,short\n")
    output = tmp_path / "out"
    run("--output", str(output), "--key", "k", "--max-bytes-per-file", "40", source)
    files = parts(output)
    assert [[row[0] for row in read(path)[1:]] for path in files] == [["1"], ["2"], ["3"]]
    assert files[1].stat().st_size > 40


def test_both_limits_cut_at_the_earliest_boundary(tmp_path):
    source = write(tmp_path / "a.csv", "k\n" + "".join(f"a{i:03d}\n" for i in range(12)))
    output = tmp_path / "out"
    run(
        "--output", str(output),
        "--key", "k",
        "--max-rows-per-file", "5",
        "--max-bytes-per-file", "20",
        source,
    )
    files = parts(output)
    # Only three 5-byte rows fit beside the header, so bytes cut before rows do.
    assert [len(read(path)) - 1 for path in files] == [3, 3, 3, 3]
    assert all(path.stat().st_size <= 20 for path in files)


def test_field_partitions_shard_independently(tmp_path):
    rows = "".join(f"g{i % 2},{i}\n" for i in range(10))
    source = write(tmp_path / "a.csv", "g,id\n" + rows)
    output = tmp_path / "out"
    run(
        "--output", str(output),
        "--key", "id",
        "--partition-by", "g",
        "--max-rows-per-file", "2",
        source,
    )
    assert tree(output) == [
        f"g=g{group}/part-{index:05d}.csv" for group in (0, 1) for index in range(3)
    ]
    assert [row[1] for row in read(output / "g=g0" / "part-00001.csv")[1:]] == ["4", "6"]


def test_descending_sort_within_each_partition(tmp_path):
    source = tmp_path / "a.tsv.gz"
    source.write_bytes(
        gzip.compress(
            b"account_id\tcreated_at\tid\n"
            b"7\t2024-01-01\t1\n9\t2024-01-03\t2\n7\t2024-02-01\t3\n"
        )
    )
    output = tmp_path / "out"
    run(
        "--output", str(output),
        "--key", "created_at,id",
        "--desc",
        "--partition-by", "account_id",
        str(source),
    )
    assert tree(output) == ["account_id=7/part-00000.csv", "account_id=9/part-00000.csv"]
    rows = read(output / "account_id=7" / "part-00000.csv")
    assert [row[1] for row in rows[1:]] == ["2024-02-01", "2024-01-01"]


def test_spilling_produces_the_same_tree(tmp_path):
    lines = "".join(f"{(i * 7919) % 97},p{i % 5},{i}\n" for i in range(4000))
    source = write(tmp_path / "a.csv", "k,p,id\n" + lines)
    spilled, in_memory = tmp_path / "spilled", tmp_path / "memory"
    for output, limit in ((spilled, "1"), (in_memory, "256")):
        run(
            "--output", str(output),
            "--key", "k,id",
            "--partition-by", "p",
            "--max-rows-per-file", "300",
            "--memory-limit-mb", limit,
            "--temp-dir", str(tmp_path),
            source,
        )
    assert tree(spilled) == tree(in_memory)
    assert [read(spilled / name) for name in tree(spilled)] == [
        read(in_memory / name) for name in tree(in_memory)
    ]
    assert not list(tmp_path.glob("merge-files-*"))


def test_partitioned_rows_match_the_single_file_output(tmp_path):
    source = write(
        tmp_path / "a.csv",
        "k,p\n3,x\n1,y\n2,x\n",
    )
    single = tmp_path / "out.csv"
    run("--output", str(single), "--key", "k", source)
    output = tmp_path / "out"
    run("--output", str(output), "--key", "k", "--partition-by", "p", source)
    partitioned = [row for name in tree(output) for row in read(output / name)[1:]]
    assert sorted(partitioned) == sorted(read(single)[1:])


def test_a_failed_run_leaves_no_output_or_temporary_directory(tmp_path, capsys):
    schema = write(
        tmp_path / "schema.json",
        json.dumps({"columns": [{"name": "k", "type": "int"}]}),
    )
    source = write(tmp_path / "a.csv", "k\n1\noops\n")
    output = tmp_path / "out"
    status = main(
        [
            "--output", str(output),
            "--key", "k",
            "--schema", schema,
            "--on-type-error", "fail",
            "--max-rows-per-file", "1",
            source,
        ]
    )
    assert status == 4
    assert 'cannot cast "oops" to int' in capsys.readouterr().err
    assert not output.exists()
    assert list(tmp_path.glob(".out.partial-*")) == []


def test_an_existing_output_directory_is_replaced(tmp_path):
    source = write(tmp_path / "a.csv", "k\n1\n")
    output = tmp_path / "out"
    (output / "stale").mkdir(parents=True)
    (output / "stale" / "part-00000.csv").write_text("k\n9\n", encoding="utf-8")
    run("--output", str(output), "--key", "k", "--max-rows-per-file", "1", source)
    assert tree(output) == ["part-00000.csv"]


def test_partitioning_to_stdout_is_a_usage_error(tmp_path, capsys):
    source = write(tmp_path / "a.csv", "k\n1\n")
    assert main(["--output", "-", "--key", "k", "--partition-by", "k", source]) == 2
    assert "must name a directory" in capsys.readouterr().err


def test_unknown_partition_column_is_an_error(tmp_path, capsys):
    source = write(tmp_path / "a.csv", "k\n1\n")
    output = str(tmp_path / "out")
    assert main(["--output", output, "--key", "k", "--partition-by", "nope", source]) == 3
    assert "partition column(s) nope" in capsys.readouterr().err


def test_limits_must_be_positive(tmp_path):
    source = write(tmp_path / "a.csv", "k\n1\n")
    with pytest.raises(SystemExit) as exit_info:
        main(["--output", str(tmp_path / "out"), "--key", "k", "--max-rows-per-file", "0", source])
    assert exit_info.value.code == 2
