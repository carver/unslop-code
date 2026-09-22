"""The two worked `Examples` at the end of the spec."""
import json

from conftest import merge, parse_csv, run, write, write_schema


# --- Spec: "Infer schema from inputs, sort by `id`, write to file:
#     python merge_files.py --output merged.csv --key id data/*.csv" -------
def test_example_one(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    write(data, "one.csv", "id,name\n3,c\n1,a\n")
    write(data, "two.csv", "id,name,extra\n2,b,z\n")
    out = tmp_path / "merged.csv"
    r = run("--output", str(out), "--key", "id",
            str(data / "one.csv"), str(data / "two.csv"), cwd=tmp_path)
    assert r.ok, r
    assert out.read_text(encoding="utf-8") == (
        "extra,id,name\n"
        ",1,a\n"
        "z,2,b\n"
        ",3,c\n"
    )


# --- Spec: "Provided schema, composite descending key, treat bad casts as
#     nulls, 128MB memory cap:
#     python merge_files.py --output - --key ts,id --desc --schema schema.json
#             --on-type-error coerce-null --memory-limit-mb 128 inputs/*.csv"
def test_example_two(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    schema = write_schema(
        tmp_path, "schema.json",
        [("id", "int"), ("ts", "timestamp"), ("amount", "float"),
         ("note", "string"), ("is_active", "bool")],
    )
    write(inputs, "a.csv",
          "id,ts,amount,note,is_active\n"
          "1,2024-07-01T12:00:00Z,2.5,hi,1\n"
          "2,2024-07-01T12:00:00Z,bad,there,0\n")
    write(inputs, "b.csv",
          "id,ts,note\n"
          "3,2024-07-01T10:00:00+02:00,later\n")
    r = run("--output", "-", "--key", "ts,id", "--desc", "--schema", str(schema),
            "--on-type-error", "coerce-null", "--memory-limit-mb", "128",
            str(inputs / "a.csv"), str(inputs / "b.csv"), cwd=tmp_path)
    assert r.ok, r
    assert r.rows() == [
        ["id", "ts", "amount", "note", "is_active"],
        ["2", "2024-07-01T12:00:00Z", "", "there", "false"],
        ["1", "2024-07-01T12:00:00Z", "2.5", "hi", "true"],
        ["3", "2024-07-01T08:00:00Z", "", "later", ""],
    ]
