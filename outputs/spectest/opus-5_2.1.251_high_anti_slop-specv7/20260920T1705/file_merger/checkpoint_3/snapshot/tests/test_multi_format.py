"""End-to-end tests for the heterogeneous inputs: TSV, JSON Lines and Parquet."""

import csv
import datetime as dt
import gzip
import json
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from merge_files import main


def write_text(path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    return str(path)


def write_gzip(path: Path, text: str) -> str:
    path.write_bytes(gzip.compress(text.encode("utf-8")))
    return str(path)


def write_jsonl(path: Path, records: list[dict]) -> str:
    return write_text(path, "".join(json.dumps(record) + "\n" for record in records))


def write_parquet(path: Path, table: dict, schema: pa.Schema | None = None) -> str:
    pq.write_table(pa.table(table, schema=schema), path)
    return str(path)


def run(tmp_path: Path, *args: str) -> list[list[str]]:
    """Run the CLI into a file and return the parsed output rows."""
    output = tmp_path / "out.csv"
    assert main(["--output", str(output), *args]) == 0
    return list(csv.reader(output.read_text(encoding="utf-8").splitlines()))


def test_mixed_sources_merge_on_a_composite_key(tmp_path):
    """The spec's first example: CSV, gzipped JSONL and Parquet by consensus."""
    users = write_text(tmp_path / "users.csv", "ts,id,src\n3,20,csv\n1,10,csv\n")
    events = write_gzip(
        tmp_path / "events.jsonl.gz",
        json.dumps({"ts": 2, "id": 15, "src": "jsonl"}) + "\n",
    )
    metrics = write_parquet(tmp_path / "metrics.parquet", {"ts": [1], "id": [11], "src": ["pq"]})
    rows = run(
        tmp_path, "--key", "ts,id", "--schema-strategy", "consensus", users, events, metrics
    )
    assert rows[0] == ["id", "src", "ts"]
    assert [row[1] for row in rows[1:]] == ["csv", "pq", "jsonl", "csv"]


def test_provided_schema_with_gzipped_tsv_descending(tmp_path, capsys):
    """The spec's second example: forced TSV and gzip, schema file, descending."""
    schema = write_text(
        tmp_path / "schema.json",
        json.dumps(
            {"columns": [{"name": "created_at", "type": "date"}, {"name": "id", "type": "int"}]}
        ),
    )
    source = write_gzip(tmp_path / "data.tsv.gz", "id\tcreated_at\tnote\n1\t2024-01-02\tx\n2\t2024-03-04\ty\n")
    status = main(
        [
            "--output", "-",
            "--key", "created_at,id",
            "--desc",
            "--schema", schema,
            "--input-format", "tsv",
            "--compression", "gzip",
            source,
        ]
    )
    assert status == 0
    assert capsys.readouterr().out == "created_at,id\n2024-03-04,2\n2024-01-02,1\n"


def test_jsonl_nulls_and_missing_keys_become_the_null_literal(tmp_path):
    source = write_jsonl(
        tmp_path / "a.jsonl",
        [{"id": 1, "note": None}, {"id": 2}, {"id": 3, "note": "here"}],
    )
    rows = run(tmp_path, "--key", "id", "--csv-null-literal", "NULL", source)
    assert rows == [["id", "note"], ["1", "NULL"], ["2", "NULL"], ["3", "here"]]


def test_jsonl_numbers_keep_int_until_they_do_not_fit(tmp_path):
    source = write_jsonl(tmp_path / "a.jsonl", [{"n": 7}, {"n": 2**70}])
    rows = run(tmp_path, "--key", "n", source)
    assert [row[0] for row in rows[1:]] == ["7.0", "1.1805916207174113e+21"]


def test_parquet_types_drive_the_output_rendering(tmp_path):
    source = write_parquet(
        tmp_path / "a.parquet",
        {
            "d": [dt.date(2024, 7, 1)],
            "ts": [dt.datetime(2024, 7, 1, 12, tzinfo=dt.timezone(dt.timedelta(hours=2)))],
            "flag": [True],
            "ratio": [1.5],
        },
    )
    rows = run(tmp_path, "--key", "d", source)
    assert rows == [["d", "flag", "ratio", "ts"], ["2024-07-01", "true", "1.5", "2024-07-01T10:00:00Z"]]


def test_parquet_streams_in_batches(tmp_path):
    table = {"k": list(range(2000)), "v": [f"row-{index}" for index in range(2000)]}
    source = write_parquet(tmp_path / "a.parquet", table)
    rows = run(
        tmp_path,
        "--key", "k",
        "--desc",
        "--memory-limit-mb", "1",
        "--parquet-row-group-bytes", "4096",
        "--temp-dir", str(tmp_path),
        source,
    )
    assert [row[1] for row in rows[1:4]] == ["row-1999", "row-1998", "row-1997"]
    assert len(rows) == 2001


def test_authoritative_prefers_the_parquet_declaration(tmp_path):
    typed = write_parquet(tmp_path / "a.parquet", {"v": [3]})
    text = write_text(tmp_path / "b.csv", "v\nnope\n")
    rows = run(tmp_path, "--key", "v", typed, text)
    assert [row[0] for row in rows[1:]] == ["", "3"]


@pytest.mark.parametrize(
    "strategy,expected",
    [("authoritative", ["1.5", "2", "3"]), ("consensus", ["", "2", "3"]), ("union", ["1.5", "2.0", "3.0"])],
)
def test_schema_strategies_settle_conflicts_differently(tmp_path, strategy, expected):
    first = write_text(tmp_path / "a.csv", "v\n2\n")
    second = write_text(tmp_path / "b.csv", "v\n3\n")
    third = write_text(tmp_path / "c.csv", "v\n1.5\n")
    rows = run(tmp_path, "--key", "v", "--schema-strategy", strategy, first, second, third)
    assert sorted(row[0] for row in rows[1:]) == sorted(expected)


def test_jsonl_ranks_with_csv_under_authoritative(tmp_path):
    """JSONL does not outrank CSV, so a disagreement still falls back to string."""
    typed = write_jsonl(tmp_path / "a.jsonl", [{"v": 2}])
    text = write_text(tmp_path / "b.csv", "v\nnope\n")
    rows = run(tmp_path, "--key", "v", typed, text)
    assert sorted(row[0] for row in rows[1:]) == ["2", "nope"]


def test_blank_lines_in_jsonl_are_ignored(tmp_path):
    source = write_text(tmp_path / "a.jsonl", '{"id": 1}\n\n   \n{"id": 2}\n')
    rows = run(tmp_path, "--key", "id", source)
    assert rows == [["id"], ["1"], ["2"]]


def test_parquet_detected_from_magic_bytes(tmp_path):
    source = write_parquet(tmp_path / "data.bin", {"id": [1]})
    assert run(tmp_path, "--key", "id", source) == [["id"], ["1"]]


def test_unknown_extension_is_a_usage_error(tmp_path, capsys):
    source = write_text(tmp_path / "data.bin", "id\n1\n")
    assert main(["--output", "-", "--key", "id", source]) == 2
    assert "cannot tell the format" in capsys.readouterr().err


def test_compression_mismatch_is_reported(tmp_path, capsys):
    source = write_text(tmp_path / "a.csv", "id\n1\n")
    assert main(["--output", "-", "--key", "id", "--compression", "gzip", source]) == 5
    assert "is not gzip compressed" in capsys.readouterr().err


def test_tab_inside_a_tsv_field_is_reported(tmp_path, capsys):
    source = write_text(tmp_path / "a.tsv", "id\tnote\n1\thas\ttab\n")
    assert main(["--output", "-", "--key", "id", source]) == 5
    assert "literal tabs" in capsys.readouterr().err


def test_nested_jsonl_values_are_rejected(tmp_path, capsys):
    source = write_jsonl(tmp_path / "a.jsonl", [{"id": 1, "tags": ["a"]}])
    assert main(["--output", "-", "--key", "id", source]) == 6
    assert "nested values" in capsys.readouterr().err


def test_nested_parquet_columns_are_rejected(tmp_path, capsys):
    source = write_parquet(tmp_path / "a.parquet", {"id": [1], "tags": [["a", "b"]]})
    assert main(["--output", "-", "--key", "id", source]) == 6
    assert "nested types" in capsys.readouterr().err


def test_invalid_jsonl_line_is_reported(tmp_path, capsys):
    source = write_text(tmp_path / "a.jsonl", '{"id": 1}\nnot json\n')
    assert main(["--output", "-", "--key", "id", source]) == 5
    assert "invalid JSON" in capsys.readouterr().err


def test_a_failed_run_leaves_no_output_behind(tmp_path):
    """The output file is renamed into place only once the merge succeeds."""
    schema = write_text(
        tmp_path / "schema.json", json.dumps({"columns": [{"name": "n", "type": "int"}]})
    )
    source = write_jsonl(tmp_path / "a.jsonl", [{"n": 1}, {"n": "oops"}])
    output = tmp_path / "out.csv"
    status = main(
        [
            "--output", str(output),
            "--key", "n",
            "--schema", schema,
            "--on-type-error", "fail",
            source,
        ]
    )
    assert status == 1
    assert sorted(path.name for path in tmp_path.iterdir()) == ["a.jsonl", "schema.json"]
