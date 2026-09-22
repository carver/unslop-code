"""Spec section: Usage / command-line interface."""
from conftest import run_tool, write_csv, write_schema, parse_csv, col


def simple(tmp_path, name="a.csv", lines=("id,note", "2,b", "1,a")):
    return write_csv(tmp_path / name, list(lines))


# Phrase: "python merge_files.py --output <PATH|-> --key <col>[,<col>...]
#          ... <INPUT1.csv> [<INPUT2.csv> ...]"
# Context: the documented invocation must work as written.
def test_minimal_documented_invocation(tmp_path):
    src = simple(tmp_path)
    out = tmp_path / "merged.csv"
    res = run_tool("--output", out, "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert out.exists()


# Phrase: "--output <PATH|->"
# Context: --output is a required flag.
def test_output_flag_is_required(tmp_path):
    src = simple(tmp_path)
    res = run_tool("--key", "id", src)
    assert res.returncode != 0


# Phrase: "--key <col>[,<col>...]"
# Context: --key is a required flag.
def test_key_flag_is_required(tmp_path):
    src = simple(tmp_path)
    res = run_tool("--output", "-", src)
    assert res.returncode != 0


# Phrase: "<INPUT1.csv> [<INPUT2.csv> ...]"
# Context: at least one positional input is required.
def test_at_least_one_input_required():
    res = run_tool("--output", "-", "--key", "id")
    assert res.returncode != 0


# Phrase: "<INPUT1.csv> [<INPUT2.csv> ...]"
# Context: several positional inputs are accepted and all contribute rows.
def test_multiple_positional_inputs(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id", "1", "3"])
    b = write_csv(tmp_path / "b.csv", ["id", "2"])
    c = write_csv(tmp_path / "c.csv", ["id", "4"])
    res = run_tool("--output", "-", "--key", "id", a, b, c)
    assert res.returncode == 0, res.stderr
    assert col(res.rows(), "id") == ["1", "2", "3", "4"]


# Phrase: "--key <col>[,<col>...]"
# Context: a comma separated list declares a composite key.
def test_key_accepts_comma_separated_list(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["a,b", "5,2", "5,1", "3,9"])
    res = run_tool("--output", "-", "--key", "a,b", src)
    assert res.returncode == 0, res.stderr
    assert res.rows()[1:] == [["3", "9"], ["5", "1"], ["5", "2"]]


# Phrase: "[--desc]"
# Context: --desc is an optional boolean flag.
def test_desc_is_optional_flag(tmp_path):
    src = simple(tmp_path)
    res = run_tool("--output", "-", "--key", "id", "--desc", src)
    assert res.returncode == 0, res.stderr


# Phrase: "[--infer {strict,loose}]"
# Context: only the two documented values are accepted.
def test_infer_rejects_unknown_mode(tmp_path):
    src = simple(tmp_path)
    res = run_tool("--output", "-", "--key", "id", "--infer", "wild", src)
    assert res.returncode != 0


def test_infer_accepts_documented_modes(tmp_path):
    src = simple(tmp_path)
    for mode in ("strict", "loose"):
        res = run_tool("--output", "-", "--key", "id", "--infer", mode, src)
        assert res.returncode == 0, res.stderr


# Phrase: "[--on-type-error {coerce-null,fail,keep-string}]"
# Context: only the three documented values are accepted.
def test_on_type_error_rejects_unknown_mode(tmp_path):
    src = simple(tmp_path)
    res = run_tool("--output", "-", "--key", "id",
                   "--on-type-error", "explode", src)
    assert res.returncode != 0


def test_on_type_error_accepts_documented_modes(tmp_path):
    src = simple(tmp_path)
    for mode in ("coerce-null", "fail", "keep-string"):
        res = run_tool("--output", "-", "--key", "id",
                       "--on-type-error", mode, src)
        assert res.returncode == 0, res.stderr


# Phrase: "[--memory-limit-mb <INT>]"
# Context: takes an integer.
def test_memory_limit_takes_integer(tmp_path):
    src = simple(tmp_path)
    res = run_tool("--output", "-", "--key", "id",
                   "--memory-limit-mb", "64", src)
    assert res.returncode == 0, res.stderr
    bad = run_tool("--output", "-", "--key", "id",
                   "--memory-limit-mb", "lots", src)
    assert bad.returncode != 0


# Phrase: "[--temp-dir <PATH>]"
# Context: accepts a path used for intermediate resources.
def test_temp_dir_accepted(tmp_path):
    src = simple(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    res = run_tool("--output", "-", "--key", "id", "--temp-dir", scratch, src)
    assert res.returncode == 0, res.stderr


# Phrase: "[--csv-quotechar <CHAR>] [--csv-escapechar <CHAR>]
#          [--csv-null-literal <STRING>]"
# Context: all three dialect overrides are accepted.
def test_dialect_override_flags_accepted(tmp_path):
    src = simple(tmp_path)
    res = run_tool("--output", "-", "--key", "id",
                   "--csv-quotechar", "'",
                   "--csv-escapechar", "\\",
                   "--csv-null-literal", "NULL", src)
    assert res.returncode == 0, res.stderr


# Phrase: "[--schema <SCHEMA_JSON>]"
# Context: accepts a path to the schema document.
def test_schema_flag_accepted(tmp_path):
    src = simple(tmp_path)
    schema = write_schema(tmp_path / "s.json", [("id", "int"), ("note", "string")])
    res = run_tool("--output", "-", "--key", "id", "--schema", schema, src)
    assert res.returncode == 0, res.stderr
    assert res.rows()[0] == ["id", "note"]


# Phrase: example "python merge_files.py --output merged.csv --key id data/*.csv"
# Context: the first documented example, with shell-expanded inputs.
def test_documented_example_one(tmp_path):
    data = tmp_path / "data"
    write_csv(data / "one.csv", ["id,name", "3,c", "1,a"])
    write_csv(data / "two.csv", ["id,name", "2,b"])
    out = tmp_path / "merged.csv"
    res = run_tool("--output", out, "--key", "id",
                   data / "one.csv", data / "two.csv")
    assert res.returncode == 0, res.stderr
    rows = parse_csv(out.read_text(encoding="utf-8"))
    assert rows == [["id", "name"], ["1", "a"], ["2", "b"], ["3", "c"]]


# Phrase: example "--output - --key ts,id --desc --schema schema.json
#          --on-type-error coerce-null --memory-limit-mb 128 inputs/*.csv"
# Context: the second documented example end to end.
def test_documented_example_two(tmp_path):
    inputs = tmp_path / "inputs"
    write_csv(inputs / "a.csv",
              ["id,ts,amount,note,is_active",
               "1,2024-07-01T12:00:00Z,1.5,hello,true"])
    write_csv(inputs / "b.csv",
              ["id,ts,amount,note,is_active",
               "2,2024-07-01T10:00:00Z,2.5,bye,false"])
    schema = write_schema(tmp_path / "schema.json", [
        ("id", "int"), ("ts", "timestamp"), ("amount", "float"),
        ("note", "string"), ("is_active", "bool"),
    ])
    res = run_tool("--output", "-", "--key", "ts,id", "--desc",
                   "--schema", schema, "--on-type-error", "coerce-null",
                   "--memory-limit-mb", "128",
                   inputs / "a.csv", inputs / "b.csv")
    assert res.returncode == 0, res.stderr
    rows = res.rows()
    assert rows[0] == ["id", "ts", "amount", "note", "is_active"]
    assert col(rows, "id") == ["1", "2"]
