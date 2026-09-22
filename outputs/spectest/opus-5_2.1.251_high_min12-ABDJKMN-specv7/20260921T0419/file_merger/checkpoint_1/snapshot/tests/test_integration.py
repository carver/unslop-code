"""End-to-end phrases: Examples section and cross-cutting behaviour."""
from conftest import body, header


# Phrase: "python merge_files.py --output merged.csv --key id data/*.csv"
# Context: Examples; infer schema from inputs, sort by id, write to file.
def test_example_infer_and_write_file(run, work, tmp_path):
    work.csv("data/a.csv", ["id", "name"], [["3", "c"], ["1", "a"]])
    work.csv("data/b.csv", ["id", "name"], [["2", "b"]])
    out = work.path("merged.csv")
    r = run(
        "--output", out, "--key", "id",
        work.path("data/a.csv"), work.path("data/b.csv"),
    )
    assert r.ok, r.stderr
    assert out.read_text(encoding="utf-8") == "id,name\n1,a\n2,b\n3,c\n"


# Phrase: "produces one sorted CSV output"
# Context: Intro; running twice produces identical bytes (deterministic).
def test_output_is_deterministic(run, work):
    work.csv("a.csv", ["id", "v"], [["2", "x"], ["1", "y"], ["2", "z"]])
    first = run("--output", "-", "--key", "id", work.path("a.csv"))
    second = run("--output", "-", "--key", "id", work.path("a.csv"))
    assert first.ok and second.ok, first.stderr + second.stderr
    assert first.stdout == second.stdout


# Phrase: "ingests multiple CSVs, aligns their schemas"
# Context: Intro; disjoint headers are aligned into one table.
def test_disjoint_headers_are_aligned(run, work):
    work.csv("a.csv", ["id", "a"], [["1", "av"]])
    work.csv("b.csv", ["id", "b"], [["2", "bv"]])
    work.csv("c.csv", ["id", "c"], [["3", "cv"]])
    r = run(
        "--output", "-", "--key", "id",
        work.path("a.csv"), work.path("b.csv"), work.path("c.csv"),
    )
    assert r.ok, r.stderr
    assert header(r) == ["a", "b", "c", "id"]
    assert body(r) == [
        ["av", "", "", "1"],
        ["", "bv", "", "2"],
        ["", "", "cv", "3"],
    ]


# Phrase: "Missing values emitted as the null literal"
# Context: Output; a short row is padded with nulls.
def test_short_row_is_padded(run, work):
    work.write("a.csv", "id,v,w\n7,x\n")
    r = run("--output", "-", "--key", "id", work.path("a.csv"))
    assert r.ok, r.stderr
    assert body(r) == [["7", "x", ""]]


# Phrase: "All inputs are ... RFC-4180 compliant, with a header row"
# Context: Fixed CSV assumptions; a trailing blank line is not a data row.
def test_trailing_blank_line_ignored(run, work):
    work.write("a.csv", "id\n7\n\n")
    r = run("--output", "-", "--key", "id", work.path("a.csv"))
    assert r.ok, r.stderr
    assert body(r) == [["7"]]


# Phrase: "Missing values emitted as the null literal (... override with --csv-null-literal)"
# Context: Output; the configured literal is recognised on input as a null too.
def test_null_literal_recognised_on_input(run, work):
    work.csv("a.csv", ["id", "v"], [["1", "NULL"], ["2", "b"]])
    r = run(
        "--output", "-", "--key", "id", "--csv-null-literal", "NULL",
        work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1", "NULL"], ["2", "b"]]


# Phrase: "write to stdout"
# Context: Output; nothing but the CSV goes to stdout on success.
def test_stdout_contains_only_csv(run, work):
    work.csv("a.csv", ["id"], [["7"]])
    r = run("--output", "-", "--key", "id", work.path("a.csv"))
    assert r.ok, r.stderr
    assert r.stdout == "id\n7\n"


# Phrase: "otherwise write to file path"
# Context: Output; an existing file is overwritten.
def test_output_file_is_overwritten(run, work):
    out = work.path("out.csv")
    out.write_text("stale contents\n", encoding="utf-8")
    work.csv("a.csv", ["id"], [["7"]])
    r = run("--output", out, "--key", "id", work.path("a.csv"))
    assert r.ok, r.stderr
    assert out.read_text(encoding="utf-8") == "id\n7\n"


# Phrase: "ingests multiple CSVs"
# Context: Intro; a nonexistent input is an error, not a silent skip.
def test_missing_input_file_is_error(run, work):
    work.csv("a.csv", ["id"], [["1"]])
    r = run("--output", "-", "--key", "id", work.path("a.csv"), work.path("nope.csv"))
    assert r.returncode != 0
    assert r.stderr.strip() != ""
