"""End-to-end tests for the CSV, TSV, JSON Lines and Parquet inputs."""

from __future__ import annotations

import gzip
import json
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from helpers import merged_rows, run_cli


def write_text(path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    return str(path)


def write_gzip(path: Path, text: str) -> str:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(text)
    return str(path)


def write_jsonl(path: Path, documents: list[dict]) -> str:
    return write_text(path, "".join(json.dumps(document) + "\n" for document in documents))


def write_parquet(path: Path, columns: dict) -> str:
    pq.write_table(pa.table(columns), path)
    return str(path)


@pytest.fixture
def mixed(tmp_path: Path) -> tuple[str, str, str]:
    """A CSV, a gzipped JSON Lines file and a Parquet file sharing ``ts`` and ``id``."""
    users = write_text(
        tmp_path / "users.csv",
        "id,ts,name\n7,2024-05-02T09:30:00Z,ada\n3,2024-05-01T08:00:00Z,grace\n",
    )
    events = write_gzip(
        tmp_path / "events.jsonl.gz",
        '{"id": 5, "ts": "2024-05-01T09:00:00Z", "kind": "click"}\n'
        "\n"
        '{"id": 9, "ts": "2024-05-03T00:00:00+02:00", "kind": null}\n',
    )
    metrics = write_parquet(
        tmp_path / "metrics.parquet",
        {
            "id": pa.array([4, 1], pa.int64()),
            "ts": pa.array(["2024-05-01T09:00:00Z", "2024-05-04T12:00:00Z"]),
            "metric": pa.array([1.5, None], pa.float64()),
        },
    )
    return users, events, metrics


def test_merges_csv_jsonl_and_parquet_on_a_composite_key(mixed):
    rows = merged_rows("--key", "ts,id", "--schema-strategy", "consensus", *mixed)
    assert rows[0] == ["id", "kind", "metric", "name", "ts"]
    assert [row[0] for row in rows[1:]] == ["3", "4", "5", "7", "9", "1"]
    # The Parquet null and the JSON null both become the null literal.
    assert rows[2] == ["4", "", "1.5", "", "2024-05-01T09:00:00Z"]


def test_offsets_are_normalised_so_mixed_sources_sort_together(mixed):
    rows = merged_rows("--key", "ts,id", *mixed)
    assert [row[4] for row in rows[1:]] == [
        "2024-05-01T08:00:00Z",
        "2024-05-01T09:00:00Z",
        "2024-05-01T09:00:00Z",
        "2024-05-02T09:30:00Z",
        "2024-05-02T22:00:00Z",
        "2024-05-04T12:00:00Z",
    ]


def test_ties_across_sources_keep_input_order(mixed):
    # The Parquet row and the JSON Lines row share a timestamp; the command
    # line order decides, whichever way the key is sorted.
    users, events, metrics = mixed
    ascending = merged_rows("--key", "ts", users, events, metrics)
    assert [row[0] for row in ascending[2:4]] == ["5", "4"]
    descending = merged_rows("--key", "ts", "--desc", metrics, events, users)
    assert [row[0] for row in descending[4:6]] == ["4", "5"]


def test_a_given_schema_fixes_the_columns_across_formats(tmp_path, mixed):
    schema = tmp_path / "schema.json"
    schema.write_text(
        json.dumps(
            {
                "columns": [
                    {"name": "ts", "type": "timestamp"},
                    {"name": "id", "type": "int"},
                    {"name": "absent", "type": "float"},
                ]
            }
        ),
        encoding="utf-8",
    )
    rows = merged_rows("--key", "id", "--schema", str(schema), "--csv-null-literal", "NULL", *mixed)
    assert rows[0] == ["ts", "id", "absent"]
    assert rows[1] == ["2024-05-04T12:00:00Z", "1", "NULL"]


def test_tsv_is_read_with_the_tab_delimiter_and_no_quoting(tmp_path):
    source = write_text(tmp_path / "a.tsv", 'id\tnote\n2\t"quoted"\n1\ta,b\n')
    rows = merged_rows("--key", "id", source)
    assert rows[1:] == [["1", "a,b"], ["2", '"quoted"']]


def test_gzip_can_be_forced_for_inputs_that_do_not_say_so(tmp_path):
    source = write_gzip(tmp_path / "a.tsv.hidden", "id\tnote\n4\tone\n")
    rows = merged_rows("--key", "id", "--input-format", "tsv", "--compression", "gzip", source)
    assert rows[1:] == [["4", "one"]]


def test_ndjson_and_parquet_magic_bytes_are_recognised(tmp_path):
    ndjson = write_jsonl(tmp_path / "a.ndjson", [{"id": 2}])
    parquet = write_parquet(tmp_path / "mystery", {"id": pa.array([1], pa.int64())})
    assert merged_rows("--key", "id", ndjson, parquet)[1:] == [["1"], ["2"]]


def test_jsonl_values_keep_the_type_json_gave_them(tmp_path):
    source = write_jsonl(
        tmp_path / "a.jsonl",
        [
            {"id": 1, "big": 2**70, "flag": True, "ratio": 2.5},
            {"id": 2, "big": 7, "flag": False, "ratio": 1},
        ],
    )
    rows = merged_rows("--key", "id", "--schema-strategy", "union", source)
    assert rows[0] == ["big", "flag", "id", "ratio"]
    # An integer beyond 64 bits widens to a float, which the column follows.
    assert rows[1] == ["1.1805916207174113e+21", "true", "1", "2.5"]
    assert rows[2] == ["7.0", "false", "2", "1.0"]


def test_strategies_settle_a_disagreement_differently(tmp_path):
    first = write_text(tmp_path / "a.csv", "id,v\n1,10\n")
    second = write_text(tmp_path / "b.csv", "id,v\n2,20\n")
    third = write_jsonl(tmp_path / "c.jsonl", [{"id": 3, "v": 1.5}])

    def values(strategy: str) -> list[str]:
        rows = merged_rows("--key", "id", "--schema-strategy", strategy, first, second, third)
        return [row[1] for row in rows[1:]]

    # The typed source decides; the two CSV files widen to it.
    assert values("authoritative") == ["10.0", "20.0", "1.5"]
    # Two files out of three call the column an int, so 1.5 will not cast.
    assert values("consensus") == ["10", "20", ""]
    # The one type that holds every value.
    assert values("union") == ["10.0", "20.0", "1.5"]


def test_parquet_types_are_taken_from_the_file_schema(tmp_path):
    source = write_parquet(
        tmp_path / "a.parquet",
        {"id": pa.array([1], pa.int64()), "when": pa.array([date(2024, 5, 1)], pa.date32())},
    )
    other = write_text(tmp_path / "b.csv", "id,when\n2,not-a-date\n")
    rows = merged_rows("--key", "id", "--schema-strategy", "authoritative", source, other)
    assert rows[1:] == [["1", "2024-05-01"], ["2", ""]]


def test_parquet_streams_in_batches(tmp_path):
    source = write_parquet(
        tmp_path / "big.parquet", {"id": pa.array([(index * 7919) % 500 for index in range(4000)])}
    )
    rows = merged_rows(
        "--key", "id", "--memory-limit-mb", "0", "--parquet-row-group-bytes", "4096", source
    )
    assert [row[0] for row in rows[1:]] == sorted(
        (str((index * 7919) % 500) for index in range(4000)), key=int
    )


@pytest.mark.parametrize(
    "prepare, message, code",
    [
        (lambda path: write_text(path / "a.tsv", "a\tb\nx\ty\tz\n"), "literal tab", 5),
        (lambda path: write_text(path / "a.csv.gz", "id\n1\n"), "is not gzipped", 5),
        (lambda path: write_gzip(path / "a.csv", "id\n1\n"), "is gzipped", 5),
        (lambda path: write_text(path / "a.dat", "id\n1\n"), "cannot tell the input format", 2),
        (lambda path: write_jsonl(path / "a.jsonl", [{"id": {"a": 1}}]), "nested dict", 6),
        (lambda path: write_text(path / "a.jsonl", "[1, 2]\n"), "expected a JSON object", 6),
        (lambda path: write_text(path / "a.jsonl", '{"id": 1\n'), "invalid JSON", 5),
        (
            lambda path: write_parquet(path / "a.parquet", {"id": pa.array([[1]])}),
            "only flat Parquet schemas",
            6,
        ),
    ],
)
def test_bad_inputs_report_their_own_exit_code(tmp_path, prepare, message, code):
    result = run_cli("--output", "-", "--key", "id", prepare(tmp_path))
    assert result.returncode == code, result.stderr
    assert message in result.stderr


def test_an_unknown_key_column_exits_three(tmp_path):
    source = write_jsonl(tmp_path / "a.jsonl", [{"id": 1}])
    result = run_cli("--output", "-", "--key", "nope", source)
    assert result.returncode == 3
    assert "not in the resolved schema" in result.stderr


def test_the_output_file_only_appears_once_it_is_complete(tmp_path):
    source = write_jsonl(tmp_path / "a.jsonl", [{"id": 4}, {"id": "oops"}])
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps({"columns": [{"name": "id", "type": "int"}]}), encoding="utf-8")
    target = tmp_path / "merged.csv"
    result = run_cli(
        "--output", str(target), "--key", "id", "--schema", str(schema),
        "--on-type-error", "fail", source,
    )
    assert result.returncode == 1
    assert "cannot cast 'oops' to int" in result.stderr
    assert list(tmp_path.glob("*merged*")) == []
