"""Spec section: Examples."""
import json

from conftest import column, table


# Phrase: "python merge_files.py --output merged.csv --key id data/*.csv"
# Context: infer schema from inputs, sort by id, write to file (the shell
#   expands the glob, so the tool sees a list of paths).
def test_example_infer_and_write_to_file(run, csv_file, tmp_path):
    csv_file("data/one.csv", "id,name\n3,c\n1,a\n")
    csv_file("data/two.csv", "id,name,extra\n2,b,e\n")
    res = run("--output", "merged.csv", "--key", "id", "data/one.csv", "data/two.csv")
    assert res.returncode == 0, res.stderr
    assert (tmp_path / "merged.csv").read_text(encoding="utf-8") == (
        "extra,id,name\n,1,a\ne,2,b\n,3,c\n"
    )


# Phrase: "python merge_files.py --output - --key ts,id --desc --schema schema.json
#   --on-type-error coerce-null --memory-limit-mb 128 inputs/*.csv"
# Context: provided schema, composite descending key, bad casts as nulls.
def test_example_schema_desc_composite_key(run, csv_file, tmp_path):
    (tmp_path / "schema.json").write_text(
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
    csv_file(
        "inputs/a.csv",
        "id,ts,amount,note,is_active\n"
        "1,2024-07-01T12:00:00Z,1.5,first,true\n"
        "2,2024-07-01T12:00:00+00:00,bad,second,0\n",
    )
    csv_file("inputs/b.csv", "id,ts,note\n3,2024-06-30T23:00:00-01:00,third\n")
    res = run(
        "--output", "-", "--key", "ts,id", "--desc", "--schema", "schema.json",
        "--on-type-error", "coerce-null", "--memory-limit-mb", "128",
        "inputs/a.csv", "inputs/b.csv",
    )
    assert res.returncode == 0, res.stderr
    assert table(res.stdout) == [
        ["id", "ts", "amount", "note", "is_active"],
        ["2", "2024-07-01T12:00:00Z", "", "second", "false"],
        ["1", "2024-07-01T12:00:00Z", "1.5", "first", "true"],
        ["3", "2024-07-01T00:00:00Z", "", "third", ""],
    ]
