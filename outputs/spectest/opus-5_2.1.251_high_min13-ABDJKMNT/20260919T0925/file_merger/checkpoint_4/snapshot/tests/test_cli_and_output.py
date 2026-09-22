"""CLI surface, output destination, and the deterministic output dialect."""


def test_single_output_with_header_and_all_rows(run_cli, csv_file):
    # Spec: "Single CSV with header row and all rows from inputs, sorted globally by the key(s)"
    a = csv_file("a.csv", "id,note\n3,c\n1,a\n")
    b = csv_file("b.csv", "id,note\n2,b\n")
    result = run_cli("--output", "-", "--key", "id", a, b)
    assert result.returncode == 0, result.stderr
    assert result.rows == [["id", "note"], ["1", "a"], ["2", "b"], ["3", "c"]]


def test_output_dash_writes_to_stdout(run_cli, csv_file):
    # Spec: "If `--output -`: write to stdout"
    a = csv_file("a.csv", "id\n7\n")
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "id\n7\n"


def test_output_path_writes_to_file(run_cli, csv_file, tmp_path):
    # Spec: "otherwise write to file path"
    a = csv_file("a.csv", "id\n2\n1\n")
    out = tmp_path / "merged.csv"
    result = run_cli("--output", out, "--key", "id", a)
    assert result.returncode == 0, result.stderr
    assert out.read_text(encoding="utf-8") == "id\n1\n2\n"
    assert result.stdout == ""


def test_output_header_matches_resolved_schema_order(run_cli, csv_file, tmp_path):
    # Spec: "Columns in output header must match the resolved schema order"
    schema = tmp_path / "schema.json"
    schema.write_text(
        '{"columns": [{"name": "note", "type": "string"}, {"name": "id", "type": "int"}]}',
        encoding="utf-8",
    )
    a = csv_file("a.csv", "id,note\n1,x\n")
    result = run_cli("--output", "-", "--key", "id", "--schema", schema, a)
    assert result.rows == [["note", "id"], ["x", "1"]]


def test_missing_values_use_empty_null_literal_by_default(run_cli, csv_file):
    # Spec: "Missing values emitted as the null literal (default empty string...)"
    a = csv_file("a.csv", "id,note\n1,\n")
    b = csv_file("b.csv", "id\n2\n")
    result = run_cli("--output", "-", "--key", "id", a, b)
    assert result.rows == [["id", "note"], ["1", ""], ["2", ""]]


def test_null_literal_override(run_cli, csv_file):
    # Spec: "(default empty string; override with `--csv-null-literal`)"
    a = csv_file("a.csv", "id,note\n1,\n")
    b = csv_file("b.csv", "id\n2\n")
    result = run_cli("--output", "-", "--key", "id", "--csv-null-literal", "NULL", a, b)
    assert result.rows == [["id", "note"], ["1", "NULL"], ["2", "NULL"]]


def test_output_quotes_by_doubling_with_comma_delimiter(run_cli, csv_file):
    # Spec: "Output delimiter `,`, quote `\"`; escape by doubling quotes; `\\n` line endings"
    a = csv_file("a.csv", 'id,note\n5,"has ""quote"", and comma"\n')
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.stdout == 'id,note\n5,"has ""quote"", and comma"\n'


def test_quotechar_override_applies_to_input_and_output(run_cli, csv_file):
    # Spec: "Quote character defaults to `\"` ... overrideable via flags", and checkpoint 2's
    # "Use configured CSV dialect flags for output quoting/escaping" (AMBIGUITIES T7)
    a = csv_file("a.csv", "id,note\n5,'a,b'\n")
    result = run_cli("--output", "-", "--key", "id", "--csv-quotechar", "'", a)
    assert result.stdout == "id,note\n5,'a,b'\n"


def test_escapechar_override_applies_to_input_and_output(run_cli, csv_file):
    # Spec: "escape character defaults to doubling the quote (`\"\"`), overrideable via flags",
    # and checkpoint 2's "Use configured CSV dialect flags ..." (AMBIGUITIES T7)
    a = csv_file("a.csv", 'id,note\n5,"a\\"b"\n')
    result = run_cli("--output", "-", "--key", "id", "--csv-escapechar", "\\", a)
    assert result.stdout == 'id,note\n5,a\\"b\n'


def test_utf8_inputs_round_trip(run_cli, csv_file):
    # Spec: "All inputs are UTF-8, RFC-4180 compliant, with a header row"
    a = csv_file("a.csv", "id,note\n5,héllo ☃\n")
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.rows == [["id", "note"], ["5", "héllo ☃"]]


def test_header_only_input_yields_header_only_output(run_cli, csv_file):
    # Spec: "with a header row" + "all rows from inputs"
    a = csv_file("a.csv", "id,note\n")
    result = run_cli("--output", "-", "--key", "id", a)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "id,note\n"


def test_key_column_absent_from_schema_is_an_error(run_cli, csv_file, tmp_path):
    # Spec: "If a key column is not present in resolved schema, that is an error"
    schema = tmp_path / "schema.json"
    schema.write_text('{"columns": [{"name": "id", "type": "int"}]}', encoding="utf-8")
    a = csv_file("a.csv", "id,note\n1,x\n")
    result = run_cli("--output", "-", "--key", "note", "--schema", schema, a)
    assert result.returncode == 3
    assert "note" in result.stderr


def test_key_column_absent_from_inferred_schema_is_an_error(run_cli, csv_file):
    # Spec: "If a key column is not present in resolved schema, that is an error"
    a = csv_file("a.csv", "id,note\n1,x\n")
    result = run_cli("--output", "-", "--key", "nope", a)
    assert result.returncode == 3
    assert "nope" in result.stderr


def test_missing_required_arguments_fail(run_cli, csv_file):
    # Spec usage: `--output` and `--key` are mandatory, inputs are variadic
    a = csv_file("a.csv", "id\n1\n")
    assert run_cli("--key", "id", a).returncode != 0
    assert run_cli("--output", "-", a).returncode != 0
    assert run_cli("--output", "-", "--key", "id").returncode != 0
