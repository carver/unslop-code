"""End-to-end tests driving the CLI the way a user would."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def write_csv(path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    return str(path)


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "merge_files.py"), *args],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


def merged_rows(*args: str) -> list[list[str]]:
    result = run_cli("--output", "-", *args)
    assert result.returncode == 0, result.stderr
    return list(csv.reader(result.stdout.splitlines()))


@pytest.fixture
def inputs(tmp_path: Path) -> tuple[str, str]:
    first = write_csv(
        tmp_path / "a.csv",
        'id,ts,amount,note\n3,2024-07-01T12:00:00+02:00,1.5,"hello, world"\n'
        '1,2024-07-02T00:00:00Z,2,plain\n2,2024-07-01T00:00:00,3.25,"say ""hi"""\n',
    )
    second = write_csv(
        tmp_path / "b.csv", "id,note,extra,is_active\n5,beta,drop-me,true\n1,alpha,drop-me,0\n"
    )
    return first, second


def test_infers_union_schema_in_lexicographic_order(inputs):
    rows = merged_rows("--key", "id", *inputs)
    assert rows[0] == ["amount", "extra", "id", "is_active", "note", "ts"]
    assert [row[2] for row in rows[1:]] == ["1", "1", "2", "3", "5"]


def test_ties_keep_input_appearance_order(inputs):
    rows = merged_rows("--key", "id", *inputs)
    assert [row[4] for row in rows[1:3]] == ["plain", "alpha"]


def test_descending_keeps_ties_in_input_order(inputs):
    rows = merged_rows("--key", "id", "--desc", *inputs)
    assert [row[2] for row in rows[1:]] == ["5", "3", "2", "1", "1"]
    assert [row[4] for row in rows[4:]] == ["plain", "alpha"]


def test_missing_columns_become_the_null_literal(inputs):
    rows = merged_rows("--key", "id", "--csv-null-literal", "NULL", *inputs)
    beta = next(row for row in rows if row[4] == "beta")
    assert beta[0] == "NULL" and beta[5] == "NULL"


def test_extra_input_columns_are_dropped_when_a_schema_is_given(tmp_path, inputs):
    schema = tmp_path / "schema.json"
    schema.write_text(
        json.dumps(
            {
                "columns": [
                    {"name": "id", "type": "int"},
                    {"name": "ts", "type": "timestamp"},
                    {"name": "amount", "type": "float"},
                    {"name": "note", "type": "string"},
                    {"name": "is_active", "type": "bool"},
                ]
            }
        ),
        encoding="utf-8",
    )
    rows = merged_rows("--key", "ts,id", "--schema", str(schema), *inputs)
    assert rows[0] == ["id", "ts", "amount", "note", "is_active"]
    # Nulls first ascending, then timestamps normalised to UTC.
    assert [row[1] for row in rows[1:]] == [
        "",
        "",
        "2024-07-01T00:00:00Z",
        "2024-07-01T10:00:00Z",
        "2024-07-02T00:00:00Z",
    ]
    assert [row[0] for row in rows[1:3]] == ["1", "5"]


def test_nulls_sort_last_when_descending(tmp_path):
    source = write_csv(tmp_path / "n.csv", "id,score\n1,5\n2,\n3,9\n")
    rows = merged_rows("--key", "score", "--desc", "--infer", "loose", source)
    assert [row[0] for row in rows[1:]] == ["3", "1", "2"]


def test_strict_infers_string_when_files_disagree(tmp_path):
    first = write_csv(tmp_path / "s1.csv", "id\n10\n")
    second = write_csv(tmp_path / "s2.csv", "id\nabc\n")
    rows = merged_rows("--key", "id", first, second)
    assert [row[0] for row in rows[1:]] == ["10", "abc"]


def test_loose_ignores_empty_cells_during_inference(tmp_path):
    source = write_csv(tmp_path / "l.csv", "id,note\n10,a\n,b\n9,c\n")
    assert [row[0] for row in merged_rows("--key", "id", "--infer", "loose", source)[1:]] == [
        "",
        "9",
        "10",
    ]
    # Strict treats the empty cell as an observation, so the column stays text.
    assert [row[0] for row in merged_rows("--key", "id", source)[1:]] == ["", "10", "9"]


def test_type_error_policies(tmp_path):
    schema = tmp_path / "s.json"
    schema.write_text(json.dumps({"columns": [{"name": "id", "type": "int"}]}), encoding="utf-8")
    source = write_csv(tmp_path / "t.csv", "id\n7\noops\n")

    assert [row[0] for row in merged_rows("--key", "id", "--schema", str(schema), source)[1:]] == ["", "7"]

    kept = merged_rows("--key", "id", "--schema", str(schema), "--on-type-error", "keep-string", source)
    assert [row[0] for row in kept[1:]] == ["7", "oops"]

    failed = run_cli(
        "--output", "-", "--key", "id", "--schema", str(schema), "--on-type-error", "fail", source
    )
    assert failed.returncode != 0
    assert "cannot cast 'oops' to int" in failed.stderr


def test_unknown_key_column_is_an_error(inputs):
    result = run_cli("--output", "-", "--key", "nope", *inputs)
    assert result.returncode != 0
    assert "not in the resolved schema" in result.stderr


def test_custom_quote_and_escape_characters(tmp_path):
    source = write_csv(tmp_path / "q.csv", "id,note\n1,|a,b|\n2,plain\n")
    result = run_cli("--output", "-", "--key", "id", "--csv-quotechar", "|", source)
    assert result.stdout == 'id,note\n1,"a,b"\n2,plain\n'


def test_writes_to_a_file(tmp_path, inputs):
    target = tmp_path / "merged.csv"
    assert run_cli("--output", str(target), "--key", "id", *inputs).returncode == 0
    assert target.read_text(encoding="utf-8").startswith("amount,extra,id,is_active,note,ts\n")


def test_spilling_matches_an_in_memory_sort(tmp_path):
    rows = [(i * 7919 % 1000, f"row-{i}") for i in range(2000)]
    source = write_csv(
        tmp_path / "big.csv", "id,note\n" + "".join(f"{key},{note}\n" for key, note in rows)
    )
    temp_dir = tmp_path / "spill"
    temp_dir.mkdir()
    spilled = merged_rows(
        "--key", "id", "--memory-limit-mb", "0", "--temp-dir", str(temp_dir), source
    )
    assert spilled == merged_rows("--key", "id", source)
    assert [row[0] for row in spilled[1:]] == [str(key) for key, _ in sorted(rows, key=lambda r: r[0])]
    assert list(temp_dir.iterdir()) == []
