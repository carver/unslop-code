"""Spec section: Output."""
from conftest import run_tool, write_csv, write_schema, parse_csv, col


# Phrase: "Single CSV with header row and all rows from inputs"
# Context: every data row of every input appears exactly once.
def test_all_rows_from_all_inputs_present(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id", "1", "2", "3"])
    b = write_csv(tmp_path / "b.csv", ["id", "4", "5"])
    res = run_tool("--output", "-", "--key", "id", a, b)
    assert col(res.rows(), "id") == ["1", "2", "3", "4", "5"]


# Phrase: "Single CSV with header row"
# Context: exactly one header row is emitted for the whole merge.
def test_single_header_row_emitted(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id,name", "1,a"])
    b = write_csv(tmp_path / "b.csv", ["id,name", "2,b"])
    rows = run_tool("--output", "-", "--key", "id", a, b).rows()
    assert rows[0] == ["id", "name"]
    assert all(r != ["id", "name"] for r in rows[1:])


# Phrase: "sorted globally by the key(s)"
# Context: ordering spans file boundaries, it is not per-file.
def test_sorted_globally_across_files(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id", "1", "5"])
    b = write_csv(tmp_path / "b.csv", ["id", "2", "4"])
    c = write_csv(tmp_path / "c.csv", ["id", "3"])
    res = run_tool("--output", "-", "--key", "id", a, b, c)
    assert col(res.rows(), "id") == ["1", "2", "3", "4", "5"]


# Phrase: "If --output -: write to stdout"
# Context: the merged CSV goes to stdout and nothing is created on disk.
def test_output_dash_writes_stdout(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id", "7"])
    res = run_tool("--output", "-", "--key", "id", src, cwd=tmp_path)
    assert res.returncode == 0, res.stderr
    assert res.stdout == "id\n7\n"
    assert not (tmp_path / "-").exists()


# Phrase: "otherwise write to file path"
# Context: the merged CSV is written to the named path, not stdout.
def test_output_path_writes_file(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id", "2", "1"])
    out = tmp_path / "sub" / "merged.csv"
    out.parent.mkdir()
    res = run_tool("--output", out, "--key", "id", src)
    assert res.returncode == 0, res.stderr
    assert res.stdout == ""
    assert out.read_text(encoding="utf-8") == "id\n1\n2\n"


# Phrase: "Columns in output header must match the resolved schema order"
# Context: with an explicit schema the declared order wins over input order.
def test_header_follows_schema_order(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["b,a,c", "1,2,3"])
    schema = write_schema(tmp_path / "s.json",
                          [("c", "string"), ("a", "string"), ("b", "string")])
    res = run_tool("--output", "-", "--key", "a", "--schema", schema, src)
    assert res.rows()[0] == ["c", "a", "b"]
    assert res.rows()[1] == ["3", "2", "1"]


# Phrase: "Columns in output header must match the resolved schema order"
# Context: with an inferred schema the resolved (lexicographic) order wins.
def test_header_follows_inferred_order(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["zeta,alpha,mid", "7,8,9"])
    res = run_tool("--output", "-", "--key", "alpha", src)
    assert res.rows()[0] == ["alpha", "mid", "zeta"]
    assert res.rows()[1] == ["8", "9", "7"]


# Phrase: "Missing values emitted as the null literal (default empty string)"
# Context: a column absent from an input yields the default empty null.
def test_missing_value_default_null_literal(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id,name", "1,x"])
    b = write_csv(tmp_path / "b.csv", ["id", "2"])
    res = run_tool("--output", "-", "--key", "id", a, b)
    assert res.rows() == [["id", "name"], ["1", "x"], ["2", ""]]


# Phrase: "override with --csv-null-literal"
# Context: the override string is emitted in place of missing values.
def test_null_literal_override_emitted(tmp_path):
    a = write_csv(tmp_path / "a.csv", ["id,name", "1,x"])
    b = write_csv(tmp_path / "b.csv", ["id", "2"])
    res = run_tool("--output", "-", "--key", "id",
                   "--csv-null-literal", "NULL", a, b)
    assert res.rows() == [["id", "name"], ["1", "x"], ["2", "NULL"]]


# Phrase: "Missing values emitted as the null literal"
# Context: a short data row leaves trailing columns null.
def test_short_row_pads_with_null(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["id,name,note", "7,only"])
    res = run_tool("--output", "-", "--key", "id", src)
    assert res.rows()[1] == ["7", "only", ""]
