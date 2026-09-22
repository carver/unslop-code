"""Spec section: Deliverables / Usage / Output."""

from conftest import (body, col, header, lines, read_text, rows_of, run, run_ok,
                      write, write_schema)

A = "id,name\n2,b\n1,a\n"
B = "id,name\n3,c\n"


# --- Spec: "Write `merge_files.py` with the following interface." ---
# Context: Deliverables. The tool is invoked as `python merge_files.py ...`.
def test_script_exists_and_runs(ws):
    a = write(ws / "a.csv", A)
    res = run("--output", "-", "--key", "id", a)
    assert res.ok, res


# --- Spec: "--output <PATH|->" / "otherwise write to file path" ---
# Context: Output. A non-dash --output value names the destination file.
def test_output_to_file_path(ws):
    a = write(ws / "a.csv", A)
    out = ws / "merged.csv"
    res = run_ok("--output", str(out), "--key", "id", a)
    assert res.stdout == ""
    assert read_text(out) == "id,name\n1,a\n2,b\n"


# --- Spec: "If `--output -`: write to stdout" ---
# Context: Output.
def test_output_dash_writes_stdout(ws):
    a = write(ws / "a.csv", A)
    res = run_ok("--output", "-", "--key", "id", a)
    assert res.stdout == "id,name\n1,a\n2,b\n"


# --- Spec: "--output -" writes nothing to a file named '-' ---
# Context: Output; `-` is the stdout sentinel, not a filename.
def test_output_dash_creates_no_file_named_dash(ws):
    a = write(ws / "a.csv", A)
    run_ok("--output", "-", "--key", "id", a, cwd=ws)
    assert not (ws / "-").exists()


# --- Spec: "<INPUT1.csv> [<INPUT2.csv> ...]" ---
# Context: Usage. One or more positional input paths.
def test_single_input_accepted(ws):
    a = write(ws / "a.csv", A)
    res = run_ok("--output", "-", "--key", "id", a)
    assert body(res.stdout) == ["1,a", "2,b"]


# --- Spec: "all rows from inputs" across multiple positional inputs ---
# Context: Output. Every data row of every input appears exactly once.
def test_multiple_inputs_all_rows_present(ws):
    a = write(ws / "a.csv", A)
    b = write(ws / "b.csv", B)
    res = run_ok("--output", "-", "--key", "id", a, b)
    assert body(res.stdout) == ["1,a", "2,b", "3,c"]


# --- Spec: "Single CSV with header row" ---
# Context: Output. Exactly one header row, first.
def test_single_header_row_only(ws):
    a = write(ws / "a.csv", A)
    b = write(ws / "b.csv", B)
    res = run_ok("--output", "-", "--key", "id", a, b)
    out = lines(res.stdout)
    assert out[0] == "id,name"
    assert out.count("id,name") == 1


# --- Spec: "Columns in output header must match the resolved schema order" ---
# Context: Output + Schema Resolution (explicit schema case).
def test_header_matches_schema_order(ws):
    a = write(ws / "a.csv", "name,id\nx,1\n")
    s = write_schema(ws / "s.json", [("id", "int"), ("name", "string")])
    res = run_ok("--output", "-", "--key", "id", "--schema", s, a)
    assert header(res.stdout) == ["id", "name"]
    assert body(res.stdout) == ["1,x"]


# --- Spec: "Missing values emitted as the null literal (default empty string)" ---
# Context: Output.
def test_missing_value_default_null_literal_is_empty(ws):
    a = write(ws / "a.csv", "id,name\n5,\n")
    res = run_ok("--output", "-", "--key", "id", a)
    assert body(res.stdout) == ["5,"]


# --- Spec: "override with `--csv-null-literal`" ---
# Context: Output / Usage flag [--csv-null-literal <STRING>].
def test_null_literal_override(ws):
    a = write(ws / "a.csv", "id,name\n5,\n")
    res = run_ok("--output", "-", "--key", "id", "--csv-null-literal", "NULL", a)
    assert body(res.stdout) == ["5,NULL"]


# --- Spec: "Missing columns in a file filled with null literal" ---
# Context: Schema Resolution (inferred schema); union of headers.
def test_missing_column_filled_with_null_literal(ws):
    a = write(ws / "a.csv", "id,name\n1,a\n")
    b = write(ws / "b.csv", "id,other\n2,z\n")
    res = run_ok("--output", "-", "--key", "id", "--csv-null-literal", "-", a, b)
    assert header(res.stdout) == ["id", "name", "other"]
    assert body(res.stdout) == ["1,a,-", "2,-,z"]


# --- Spec: "--key <col>" is required to name the sort column ---
# Context: Usage. Omitting --key is a usage error.
def test_missing_key_flag_is_error(ws):
    a = write(ws / "a.csv", A)
    res = run("--output", "-", a)
    assert not res.ok


# --- Spec: "--output <PATH|->" is required ---
# Context: Usage.
def test_missing_output_flag_is_error(ws):
    a = write(ws / "a.csv", A)
    res = run("--key", "id", a)
    assert not res.ok


# --- Spec: output file is a real UTF-8 CSV round-trippable by a CSV reader ---
# Context: Fixed CSV assumptions ("All inputs are UTF-8") + Output.
def test_output_is_utf8(ws):
    a = write(ws / "a.csv", "id,name\n5,héllo ☃\n")
    out = ws / "o.csv"
    run_ok("--output", str(out), "--key", "id", a)
    assert read_text(out) == "id,name\n5,héllo ☃\n"
    with open(out, "rb") as fh:
        assert "héllo ☃".encode("utf-8") in fh.read()


# --- Spec: "--memory-limit-mb <INT>" flag is accepted ---
# Context: Usage / Performance & Memory.
def test_memory_limit_flag_accepted(ws):
    a = write(ws / "a.csv", A)
    res = run_ok("--output", "-", "--key", "id", "--memory-limit-mb", "64", a)
    assert body(res.stdout) == ["1,a", "2,b"]


# --- Spec: "--temp-dir <PATH>" flag is accepted ---
# Context: Usage / Performance & Memory.
def test_temp_dir_flag_accepted(ws):
    a = write(ws / "a.csv", A)
    tmp = ws / "scratch"
    tmp.mkdir()
    res = run_ok("--output", "-", "--key", "id", "--temp-dir", str(tmp), a)
    assert body(res.stdout) == ["1,a", "2,b"]


# --- Spec example: "python merge_files.py --output merged.csv --key id data/*.csv" ---
# Context: Examples. Infer schema from inputs, sort by id, write to file.
def test_example_one_infer_and_write_file(ws):
    write(ws / "data" / "a.csv", "id,name\n3,c\n1,a\n")
    write(ws / "data" / "b.csv", "id,name\n2,b\n")
    out = ws / "merged.csv"
    run_ok("--output", str(out), "--key", "id",
           str(ws / "data" / "a.csv"), str(ws / "data" / "b.csv"))
    assert read_text(out) == "id,name\n1,a\n2,b\n3,c\n"


# --- Spec example: "--output - --key ts,id --desc --schema schema.json
#                    --on-type-error coerce-null --memory-limit-mb 128 inputs/*.csv" ---
# Context: Examples. All flags combined.
def test_example_two_all_flags_combined(ws):
    write(ws / "in" / "a.csv", "ts,id,amount\n2024-07-01T12:00:00Z,1,1.5\n")
    write(ws / "in" / "b.csv", "ts,id,amount\n2024-07-02T00:00:00+02:00,2,oops\n")
    s = write_schema(ws / "schema.json", [("id", "int"), ("ts", "timestamp"),
                                          ("amount", "float")])
    res = run_ok("--output", "-", "--key", "ts,id", "--desc", "--schema", s,
                 "--on-type-error", "coerce-null", "--memory-limit-mb", "128",
                 str(ws / "in" / "a.csv"), str(ws / "in" / "b.csv"))
    assert header(res.stdout) == ["id", "ts", "amount"]
    assert col(res.stdout, "ts") == ["2024-07-01T22:00:00Z", "2024-07-01T12:00:00Z"]
    assert col(res.stdout, "amount") == ["", "1.5"]


# --- Spec: "all rows from inputs" — header-only input contributes no rows ---
# Context: Output; see AMBIGUITIES T22.
def test_header_only_input_contributes_no_rows(ws):
    a = write(ws / "a.csv", "id,name\n")
    b = write(ws / "b.csv", "id,name\n5,a\n")
    res = run_ok("--output", "-", "--key", "id", a, b)
    assert lines(res.stdout) == ["id,name", "5,a"]


# --- Spec: output still carries its header when no data rows exist ---
# Context: Output; see AMBIGUITIES T22.
def test_header_only_output(ws):
    a = write(ws / "a.csv", "id,name\n")
    res = run_ok("--output", "-", "--key", "id", a)
    assert res.stdout == "id,name\n"
