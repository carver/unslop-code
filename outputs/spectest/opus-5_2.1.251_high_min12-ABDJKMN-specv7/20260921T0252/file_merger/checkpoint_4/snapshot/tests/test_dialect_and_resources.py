"""Spec sections: Deterministic Dialect Details, Performance & Memory."""
import os

from conftest import run_tool, write_csv, write_schema, col


# Phrase: "Output delimiter ,"
# Context: fields are joined with commas.
def test_output_delimiter_is_comma(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["a,b", "1,2"])
    res = run_tool("--output", "-", "--key", "a", src)
    assert res.stdout.splitlines()[0] == "a,b"


# Phrase: "quote \"; escape by doubling quotes"
# Context: a value containing a quote is emitted quoted with doubled quotes.
def test_output_quotes_by_doubling(tmp_path):
    src = write_csv(tmp_path / "a.csv", ['k,v', '7,"say ""hi"""'])
    res = run_tool("--output", "-", "--key", "k", src)
    assert res.stdout.splitlines()[1] == '7,"say ""hi"""'


# Phrase: "quote \"; escape by doubling quotes"
# Context: backslash escaped input is re-emitted using doubling, never
# backslashes.
def test_output_never_uses_backslash_escapes(tmp_path):
    src = write_csv(tmp_path / "a.csv", ['k,v', '7,"a\\"b"'])
    res = run_tool("--output", "-", "--key", "k", src)
    line = res.stdout.splitlines()[1]
    assert line == '7,"a""b"'
    assert "\\" not in line


# Phrase: "Output delimiter ,, quote \""
# Context: a value containing the delimiter is quoted on output.
def test_output_quotes_embedded_delimiter(tmp_path):
    src = write_csv(tmp_path / "a.csv", ['k,v', '7,"a,b"'])
    res = run_tool("--output", "-", "--key", "k", src)
    assert res.stdout.splitlines()[1] == '7,"a,b"'


# Phrase: "\n line endings"
# Context: no carriage returns are emitted.
def test_output_line_endings_are_newlines(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["a", "1", "2"])
    res = run_tool("--output", "-", "--key", "a", src)
    assert res.stdout == "a\n1\n2\n"
    assert "\r" not in res.stdout


# Phrase: "\n line endings" for file output
# Context: file output uses the same line endings.
def test_output_file_line_endings(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["a", "7"])
    out = tmp_path / "o.csv"
    run_tool("--output", out, "--key", "a", src)
    with open(str(out), "rb") as fh:
        assert fh.read() == b"a\n7\n"


# Phrase: "header row first"
# Context: the header is the very first emitted line.
def test_header_row_first(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["a,b", "1,2"])
    res = run_tool("--output", "-", "--key", "a", src)
    assert res.stdout.splitlines()[0] == "a,b"


# Phrase: "date stays YYYY-MM-DD"
# Context: a date column is not promoted to a timestamp shape on output.
def test_date_output_shape(tmp_path):
    schema = write_schema(tmp_path / "s.json", [("d", "date")])
    src = write_csv(tmp_path / "a.csv", ["d", "2024-07-01"])
    res = run_tool("--output", "-", "--key", "d", "--schema", schema, src)
    assert col(res.rows(), "d") == ["2024-07-01"]


# Phrase: "date stays YYYY-MM-DD"
# Context: an inferred date column keeps the plain date shape too.
def test_inferred_date_output_shape(tmp_path):
    src = write_csv(tmp_path / "a.csv", ["d", "2024-07-01", "2023-01-05"])
    res = run_tool("--output", "-", "--key", "d", src)
    assert col(res.rows(), "d") == ["2023-01-05", "2024-07-01"]


# Phrase: "timestamp normalized to UTC with Z (e.g., 2024-07-01T12:00:00Z)"
# Context: the rendered form ends with Z and has no offset.
def test_timestamp_output_shape(tmp_path):
    schema = write_schema(tmp_path / "s.json", [("ts", "timestamp")])
    src = write_csv(tmp_path / "a.csv", ["ts", "2024-07-01T12:00:00+00:00"])
    res = run_tool("--output", "-", "--key", "ts", "--schema", schema, src)
    value = col(res.rows(), "ts")[0]
    assert value == "2024-07-01T12:00:00Z"
    assert "+" not in value


# Phrase: "Tool must work under small --memory-limit-mb (e.g., 64MB) on
#          arbitrarily large inputs"
# Context: 64MB cap on an input far bigger than the in-memory budget allows.
def test_small_memory_limit_large_input(tmp_path):
    n = 60000
    lines = ["id,payload"] + ["%d,%s" % (n - i, "x" * 40) for i in range(n)]
    src = write_csv(tmp_path / "big.csv", lines)
    res = run_tool("--output", "-", "--key", "id",
                   "--memory-limit-mb", "1", src, timeout=600)
    assert res.returncode == 0, res.stderr
    ids = [int(v) for v in col(res.rows(), "id")]
    assert ids == list(range(1, n + 1))


# Phrase: "All intermediate resources must be cleaned up on exit"
# Context: the temp dir is empty again once the tool returns.
def test_temp_dir_cleaned_on_success(tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    lines = ["id"] + [str(i) for i in range(5000)]
    src = write_csv(tmp_path / "a.csv", lines)
    res = run_tool("--output", "-", "--key", "id", "--temp-dir", scratch,
                   "--memory-limit-mb", "1", src)
    assert res.returncode == 0, res.stderr
    assert os.listdir(str(scratch)) == []


# Phrase: "All intermediate resources must be cleaned up on exit"
# Context: cleanup also happens when the run aborts with an error.
def test_temp_dir_cleaned_on_failure(tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    schema = write_schema(tmp_path / "s.json", [("n", "int")])
    src = write_csv(tmp_path / "a.csv", ["n", "oops"])
    res = run_tool("--output", "-", "--key", "n", "--schema", schema,
                   "--on-type-error", "fail", "--temp-dir", scratch, src)
    assert res.returncode != 0
    assert os.listdir(str(scratch)) == []


# Phrase: "[--temp-dir <PATH>]"
# Context: intermediate files live under the requested directory, not /tmp.
def test_temp_dir_is_used(tmp_path):
    scratch = tmp_path / "scratch"
    lines = ["id"] + [str(i) for i in range(5000)]
    src = write_csv(tmp_path / "a.csv", lines)
    res = run_tool("--output", "-", "--key", "id", "--temp-dir", scratch,
                   "--memory-limit-mb", "1", src)
    assert res.returncode == 0, res.stderr
