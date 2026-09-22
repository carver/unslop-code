"""End-to-end tests driving the CLI the way a user would."""

import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from merge_files import main


def write_csv(path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    return str(path)


def run(tmp_path: Path, *args: str) -> list[list[str]]:
    """Run the CLI into a file and return the parsed output rows."""
    output = tmp_path / "out.csv"
    assert main(["--output", str(output), *args]) == 0
    return list(csv.reader(output.read_text(encoding="utf-8").splitlines()))


def test_union_of_headers_is_lexicographic(tmp_path):
    first = write_csv(tmp_path / "a.csv", "b,a\n2,1\n")
    second = write_csv(tmp_path / "b.csv", "c,a\nx,3\n")
    rows = run(tmp_path, "--key", "a", first, second)
    assert rows[0] == ["a", "b", "c"]
    assert rows[1:] == [["1", "2", ""], ["3", "", "x"]]


def test_missing_and_extra_columns_follow_the_schema(tmp_path):
    schema = write_csv(
        tmp_path / "schema.json",
        json.dumps({"columns": [{"name": "id", "type": "int"}, {"name": "note", "type": "string"}]}),
    )
    source = write_csv(tmp_path / "a.csv", "id,extra\n7,dropped\n")
    rows = run(tmp_path, "--key", "id", "--schema", schema, source)
    assert rows == [["id", "note"], ["7", ""]]


def test_composite_descending_key_with_stable_ties(tmp_path):
    source = write_csv(
        tmp_path / "a.csv",
        "g,id,tag\n1,1,first\n2,1,second\n1,1,third\n",
    )
    rows = run(tmp_path, "--key", "g,id", "--desc", source)
    assert [row[2] for row in rows[1:]] == ["second", "first", "third"]


def test_nulls_sort_first_ascending_and_last_descending(tmp_path):
    source = write_csv(tmp_path / "a.csv", "k,tag\n2,b\n,none\n1,a\n")
    ascending = run(tmp_path, "--key", "k", source)
    descending = run(tmp_path, "--key", "k", "--desc", source)
    assert [row[1] for row in ascending[1:]] == ["none", "a", "b"]
    assert [row[1] for row in descending[1:]] == ["b", "a", "none"]


def test_timestamps_are_normalised_to_utc(tmp_path):
    schema = write_csv(
        tmp_path / "schema.json",
        json.dumps({"columns": [{"name": "ts", "type": "timestamp"}]}),
    )
    source = write_csv(
        tmp_path / "a.csv",
        "ts\n2024-07-01T12:00:00+02:00\n2024-07-01T12:00:00\n2024-07-01T12:00:00.5Z\n",
    )
    rows = run(tmp_path, "--key", "ts", "--schema", schema, source)
    assert [row[0] for row in rows[1:]] == [
        "2024-07-01T10:00:00Z",
        "2024-07-01T12:00:00Z",
        "2024-07-01T12:00:00.500000Z",
    ]


def test_strict_inference_falls_back_to_string_on_conflict(tmp_path):
    first = write_csv(tmp_path / "a.csv", "v\n1\n")
    second = write_csv(tmp_path / "b.csv", "v\n1.5\n")
    rows = run(tmp_path, "--key", "v", first, second)
    assert [row[0] for row in rows[1:]] == ["1", "1.5"]


def test_loose_inference_widens_to_float(tmp_path):
    first = write_csv(tmp_path / "a.csv", "v\n2\n")
    second = write_csv(tmp_path / "b.csv", "v\n1.5\n\n")
    rows = run(tmp_path, "--key", "v", "--infer", "loose", first, second)
    assert [row[0] for row in rows[1:]] == ["", "1.5", "2.0"]


def test_inference_recognises_dates_bools_and_timestamps(tmp_path):
    source = write_csv(
        tmp_path / "a.csv",
        "d,flag,ts\n2024-07-01,1,2024-07-01\n2024-01-02,0,2024-01-02T03:04:05Z\n",
    )
    rows = run(tmp_path, "--key", "d", "--infer", "loose", source)
    assert rows[1] == ["2024-01-02", "false", "2024-01-02T03:04:05Z"]
    assert rows[2] == ["2024-07-01", "true", "2024-07-01T00:00:00Z"]


@pytest.mark.parametrize(
    "policy,expected",
    [("coerce-null", ""), ("keep-string", "oops")],
)
def test_type_error_policies(tmp_path, policy, expected):
    schema = write_csv(
        tmp_path / "schema.json", json.dumps({"columns": [{"name": "n", "type": "int"}]})
    )
    source = write_csv(tmp_path / "a.csv", "n\noops\n")
    rows = run(tmp_path, "--key", "n", "--schema", schema, "--on-type-error", policy, source)
    assert rows[1] == [expected]


def test_type_error_fail_exits_non_zero(tmp_path, capsys):
    schema = write_csv(
        tmp_path / "schema.json", json.dumps({"columns": [{"name": "n", "type": "int"}]})
    )
    source = write_csv(tmp_path / "a.csv", "n\noops\n")
    status = main(
        ["--output", "-", "--key", "n", "--schema", schema, "--on-type-error", "fail", source]
    )
    assert status == 1
    assert "expects int" in capsys.readouterr().err


def test_unknown_key_column_is_an_error(tmp_path, capsys):
    source = write_csv(tmp_path / "a.csv", "a\n1\n")
    assert main(["--output", "-", "--key", "missing", source]) == 1
    assert "not in the resolved schema" in capsys.readouterr().err


def test_output_to_stdout(tmp_path, capsys):
    source = write_csv(tmp_path / "a.csv", "a\n7\n")
    assert main(["--output", "-", "--key", "a", source]) == 0
    assert capsys.readouterr().out == "a\n7\n"


def test_zero_and_one_infer_as_bool(tmp_path):
    """bool outranks int in the spec's type priority, and accepts 1/0."""
    source = write_csv(tmp_path / "a.csv", "flag\n1\n0\n")
    rows = run(tmp_path, "--key", "flag", source)
    assert [row[0] for row in rows[1:]] == ["false", "true"]


def test_quoting_and_escaping(tmp_path):
    source = write_csv(tmp_path / "a.csv", 'a,note\n1,"say ""hi"""\n2,"back \\"slash"\n')
    rows = run(tmp_path, "--key", "a", source)
    assert [row[1] for row in rows[1:]] == ['say "hi"', 'back "slash']


def test_custom_null_literal_round_trips(tmp_path):
    source = write_csv(tmp_path / "a.csv", "a,b\n1,NULL\n2,\n")
    rows = run(tmp_path, "--key", "a", "--csv-null-literal", "NULL", source)
    assert [row[1] for row in rows[1:]] == ["NULL", "NULL"]


def test_spilling_matches_in_memory_sort(tmp_path):
    lines = ["k,v"] + [f"{(i * 7919) % 1000},{i}" for i in range(5000)]
    source = write_csv(tmp_path / "a.csv", "\n".join(lines) + "\n")
    spilled = run(tmp_path, "--key", "k", "--memory-limit-mb", "1", "--temp-dir", str(tmp_path), source)
    in_memory = run(tmp_path, "--key", "k", "--memory-limit-mb", "256", source)
    assert spilled == in_memory
    assert len(spilled) == 5001
    assert not list(tmp_path.glob("merge-files-*"))
