"""End-to-end tests for partitioned and sharded output directories."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from helpers import merged_rows, run_cli


def write_csv(path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    return str(path)


def read_part(path: Path) -> list[list[str]]:
    return list(csv.reader(path.read_text(encoding="utf-8").splitlines()))


def part_files(root: Path) -> list[str]:
    """Every part file below ``root``, as posix paths relative to it, sorted."""
    return sorted(str(path.relative_to(root)) for path in root.rglob("part-*.csv"))


def data_rows(root: Path) -> list[list[str]]:
    """The data rows of every part file, in part-file order."""
    return [row for name in part_files(root) for row in read_part(root / name)[1:]]


@pytest.fixture
def events(tmp_path: Path) -> tuple[str, str]:
    """Two CSVs sharing ``ts``, ``id``, ``country`` and ``dt``; one country is missing."""
    first = write_csv(
        tmp_path / "a.csv",
        "id,ts,country,dt\n"
        "3,2024-05-01T03:00:00Z,US,2024-05-01\n"
        "1,2024-05-01T01:00:00Z,DE,2024-05-01\n"
        "4,2024-05-02T04:00:00Z,US,2024-05-02\n",
    )
    second = write_csv(
        tmp_path / "b.csv",
        "id,ts,country,dt\n"
        "2,2024-05-01T02:00:00Z,US,2024-05-01\n"
        "5,2024-05-02T05:00:00Z,,2024-05-02\n",
    )
    return first, second


def test_field_partitioning_builds_a_hive_tree(tmp_path, events):
    out = tmp_path / "out"
    assert run_cli("--output", str(out), "--key", "ts,id", "--partition-by", "country,dt", *events).returncode == 0
    assert part_files(out) == [
        "country=DE/dt=2024-05-01/part-00000.csv",
        "country=US/dt=2024-05-01/part-00000.csv",
        "country=US/dt=2024-05-02/part-00000.csv",
        "country=_null/dt=2024-05-02/part-00000.csv",
    ]


def test_each_partition_file_is_a_complete_csv(tmp_path, events):
    out = tmp_path / "out"
    run_cli("--output", str(out), "--key", "ts,id", "--partition-by", "country,dt", *events)
    rows = read_part(out / "country=US/dt=2024-05-01/part-00000.csv")
    assert rows[0] == ["country", "dt", "id", "ts"]
    assert [row[2] for row in rows[1:]] == ["2", "3"]


def test_partition_values_are_percent_encoded(tmp_path):
    source = write_csv(
        tmp_path / "p.csv", "id,name\n1,a b\n2,a/b\n3,Côte\n4,plain_1.0-x\n"
    )
    out = tmp_path / "out"
    run_cli("--output", str(out), "--key", "id", "--partition-by", "name", source)
    assert part_files(out) == [
        "name=C%C3%B4te/part-00000.csv",
        "name=a%20b/part-00000.csv",
        "name=a%2Fb/part-00000.csv",
        "name=plain_1.0-x/part-00000.csv",
    ]


def test_partition_values_come_from_the_resolved_types(tmp_path):
    """``01`` and ``1`` are one ``int`` partition; a timestamp gets its canonical form."""
    source = write_csv(
        tmp_path / "t.csv",
        "id,bucket,seen\n1,01,2024-05-01T12:00:00+02:00\n2,1,2024-05-01T10:00:00Z\n",
    )
    out = tmp_path / "out"
    run_cli("--output", str(out), "--key", "id", "--partition-by", "bucket,seen", source)
    assert part_files(out) == ["bucket=1/seen=2024-05-01T10%3A00%3A00Z/part-00000.csv"]


def test_sharding_by_rows_without_field_partitions(tmp_path):
    source = write_csv(tmp_path / "r.csv", "id\n" + "".join(f"{i}\n" for i in range(7)))
    out = tmp_path / "out"
    assert run_cli(
        "--output", str(out), "--key", "id", "--max-rows-per-file", "3", source
    ).returncode == 0
    assert part_files(out) == ["part-00000.csv", "part-00001.csv", "part-00002.csv"]
    assert [len(read_part(out / name)) - 1 for name in part_files(out)] == [3, 3, 1]
    # The stream is cut in the order the global sort emits it.
    assert [row[0] for row in data_rows(out)] == [str(i) for i in range(7)]
    assert all(read_part(out / name)[0] == ["id"] for name in part_files(out))


def test_sharding_by_bytes_keeps_every_file_within_the_limit(tmp_path):
    source = write_csv(tmp_path / "b.csv", "id,note\n" + "".join(f"{i},{'x' * 20}\n" for i in range(20)))
    out = tmp_path / "out"
    run_cli("--output", str(out), "--key", "id", "--max-bytes-per-file", "120", source)
    assert len(part_files(out)) > 1
    assert all((out / name).stat().st_size <= 120 for name in part_files(out))
    assert [row[0] for row in data_rows(out)] == [str(i) for i in range(20)]


def test_a_row_larger_than_the_byte_limit_gets_a_file_of_its_own(tmp_path):
    source = write_csv(tmp_path / "w.csv", f"id,note\n1,small\n2,{'x' * 400}\n3,small\n")
    out = tmp_path / "out"
    run_cli("--output", str(out), "--key", "id", "--max-bytes-per-file", "64", source)
    names = part_files(out)
    assert [len(read_part(out / name)) - 1 for name in names] == [1, 1, 1]
    assert (out / names[1]).stat().st_size > 64


def test_both_limits_cut_at_whichever_comes_first(tmp_path):
    source = write_csv(tmp_path / "m.csv", "id,note\n" + "".join(f"{i},{'x' * 30}\n" for i in range(12)))
    out = tmp_path / "out"
    run_cli(
        "--output", str(out), "--key", "id",
        "--max-rows-per-file", "5", "--max-bytes-per-file", "120", source,
    )
    counts = [len(read_part(out / name)) - 1 for name in part_files(out)]
    assert max(counts) <= 5
    assert all((out / name).stat().st_size <= 120 for name in part_files(out))
    assert sum(counts) == 12


def test_partitioning_and_sharding_number_parts_per_partition(tmp_path):
    source = write_csv(
        tmp_path / "c.csv",
        "id,country\n" + "".join(f"{i},{'US' if i % 2 else 'DE'}\n" for i in range(10)),
    )
    out = tmp_path / "out"
    run_cli(
        "--output", str(out), "--key", "id",
        "--partition-by", "country", "--max-rows-per-file", "2", source,
    )
    assert part_files(out) == [
        f"country={country}/part-{index:05d}.csv"
        for country in ("DE", "US")
        for index in range(3)
    ]


def test_rows_are_sorted_within_each_partition_descending(tmp_path):
    source = write_csv(
        tmp_path / "d.csv",
        "account_id,created_at,id\n"
        "7,2024-01-02,b\n9,2024-01-01,c\n7,2024-01-03,a\n7,2024-01-01,d\n",
    )
    out = tmp_path / "out"
    run_cli(
        "--output", str(out), "--key", "created_at,id", "--desc",
        "--partition-by", "account_id", source,
    )
    assert [row[2] for row in read_part(out / "account_id=7/part-00000.csv")[1:]] == ["a", "b", "d"]
    assert part_files(out) == ["account_id=7/part-00000.csv", "account_id=9/part-00000.csv"]


def test_partitioned_output_holds_the_same_rows_as_a_single_csv(tmp_path, events):
    out = tmp_path / "out"
    run_cli("--output", str(out), "--key", "ts,id", "--partition-by", "country", *events)
    assert sorted(data_rows(out)) == sorted(merged_rows("--key", "ts,id", *events)[1:])


def test_spilling_to_disk_produces_the_same_tree(tmp_path, events):
    limited, buffered = tmp_path / "limited", tmp_path / "buffered"
    for out, extra in ((limited, ["--memory-limit-mb", "0"]), (buffered, [])):
        assert run_cli(
            "--output", str(out), "--key", "ts,id",
            "--partition-by", "country,dt", "--max-rows-per-file", "1", *extra, *events,
        ).returncode == 0
    assert part_files(limited) == part_files(buffered)
    assert data_rows(limited) == data_rows(buffered)


def test_an_earlier_run_is_replaced_and_leaves_no_temporary_directories(tmp_path, events):
    out = tmp_path / "out"
    run_cli("--output", str(out), "--key", "ts,id", "--partition-by", "country,dt", *events)
    run_cli("--output", str(out), "--key", "ts,id", "--partition-by", "country", *events)
    assert part_files(out) == [
        "country=DE/part-00000.csv",
        "country=US/part-00000.csv",
        "country=_null/part-00000.csv",
    ]
    assert [path.name for path in tmp_path.iterdir() if path.name.startswith(".")] == []


def test_a_failed_run_leaves_the_previous_output_untouched(tmp_path, events):
    out = tmp_path / "out"
    run_cli("--output", str(out), "--key", "ts,id", "--partition-by", "country", *events)

    schema = tmp_path / "schema.json"
    schema.write_text(
        json.dumps(
            {
                "columns": [
                    {"name": "id", "type": "int"},
                    {"name": "ts", "type": "timestamp"},
                    {"name": "country", "type": "string"},
                ]
            }
        ),
        encoding="utf-8",
    )
    broken = write_csv(tmp_path / "broken.csv", "id,ts,country\noops,2024-05-03T00:00:00Z,US\n")
    failed = run_cli(
        "--output", str(out), "--key", "ts,id", "--partition-by", "country",
        "--schema", str(schema), "--on-type-error", "fail", *events, broken,
    )
    assert failed.returncode == 1
    assert "cannot cast" in failed.stderr
    assert part_files(out) == [
        "country=DE/part-00000.csv",
        "country=US/part-00000.csv",
        "country=_null/part-00000.csv",
    ]
    assert [path.name for path in tmp_path.iterdir() if path.name.startswith(".")] == []


def test_stdout_is_refused_when_partitioning(events):
    result = run_cli("--output", "-", "--key", "ts", "--partition-by", "country", *events)
    assert result.returncode == 2
    assert "--output must name a directory" in result.stderr


def test_a_file_cannot_be_used_as_the_output_directory(tmp_path, events):
    target = write_csv(tmp_path / "taken.csv", "id\n1\n")
    result = run_cli("--output", target, "--key", "ts", "--max-rows-per-file", "2", *events)
    assert result.returncode == 2
    assert "must name a directory" in result.stderr


def test_an_unknown_partition_column_is_an_error(events):
    result = run_cli("--output", "out", "--key", "ts", "--partition-by", "region", *events)
    assert result.returncode == 3
    assert "partition column(s) region are not in the resolved schema" in result.stderr


def test_non_positive_limits_are_refused(events):
    result = run_cli("--output", "out", "--key", "ts", "--max-rows-per-file", "0", *events)
    assert result.returncode == 2
    assert "not a positive integer" in result.stderr


def test_without_partitioning_flags_the_output_is_still_one_csv(tmp_path, events):
    target = tmp_path / "merged.csv"
    assert run_cli("--output", str(target), "--key", "ts,id", *events).returncode == 0
    assert target.is_file()
    assert len(read_part(target)) == 6
