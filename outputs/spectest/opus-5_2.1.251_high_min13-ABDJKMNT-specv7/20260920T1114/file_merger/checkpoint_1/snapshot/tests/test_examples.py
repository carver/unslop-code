"""Spec section: Examples — the two documented invocations."""

import json

from conftest import header_of, rows_of


# Phrase: "python merge_files.py --output merged.csv --key id data/*.csv"
# Context: Examples. Infer schema from inputs, sort by id, write to file.
def test_example_infer_and_write_to_file(csv_file, run_tool, workdir):
    csv_file("data/a.csv", "id,note\n3,c\n1,a\n")
    csv_file("data/b.csv", "id,note\n2,b\n")
    result = run_tool(
        "--output", "merged.csv", "--key", "id", "data/a.csv", "data/b.csv"
    )
    assert result.returncode == 0, result.stderr
    assert (workdir / "merged.csv").read_text(encoding="utf-8") == (
        "id,note\n1,a\n2,b\n3,c\n"
    )


# Phrase: "--output - --key ts,id --desc --schema schema.json
#          --on-type-error coerce-null --memory-limit-mb 128 inputs/*.csv"
# Context: Examples. Every flag of the second example together.
def test_example_schema_composite_desc_to_stdout(csv_file, run_tool):
    csv_file(
        "schema.json",
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
    )
    csv_file(
        "inputs/a.csv",
        "id,ts,amount,note,is_active\n"
        "1,2024-07-01T12:00:00Z,2.5,first,1\n"
        "2,2024-07-01T09:00:00+00:00,oops,second,0\n",
    )
    csv_file(
        "inputs/b.csv",
        "id,ts,note\n3,2024-07-01T12:00:00Z,third\n",
    )
    result = run_tool(
        "--output", "-", "--key", "ts,id", "--desc", "--schema", "schema.json",
        "--on-type-error", "coerce-null", "--memory-limit-mb", "128",
        "inputs/a.csv", "inputs/b.csv",
    )
    assert result.returncode == 0, result.stderr
    assert header_of(result.stdout) == ["id", "ts", "amount", "note", "is_active"]
    assert rows_of(result.stdout) == [
        ["3", "2024-07-01T12:00:00Z", "", "third", ""],
        ["1", "2024-07-01T12:00:00Z", "2.5", "first", "true"],
        ["2", "2024-07-01T09:00:00Z", "", "second", "false"],
    ]
