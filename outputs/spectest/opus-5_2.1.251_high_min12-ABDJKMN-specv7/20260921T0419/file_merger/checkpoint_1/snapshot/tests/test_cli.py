"""Spec section: Usage / command-line interface."""
import json
import sys

from conftest import body, header


# Phrase: "Write `merge_files.py` with the following interface."
# Context: Deliverables.
def test_script_exists_and_is_runnable(run, work):
    work.csv("a.csv", ["id"], [["1"]])
    r = run("--output", "-", "--key", "id", work.path("a.csv"))
    assert r.ok, r.stderr


# Phrase: "python merge_files.py --output <PATH|-> --key <col>[,<col>...] ... <INPUT1.csv>"
# Context: Usage; --output and --key are non-optional (no brackets), inputs are positional.
def test_missing_output_flag_is_error(run, work):
    work.csv("a.csv", ["id"], [["1"]])
    r = run("--key", "id", work.path("a.csv"))
    assert r.returncode != 0


def test_missing_key_flag_is_error(run, work):
    work.csv("a.csv", ["id"], [["1"]])
    r = run("--output", "-", work.path("a.csv"))
    assert r.returncode != 0


def test_missing_input_files_is_error(run):
    r = run("--output", "-", "--key", "id")
    assert r.returncode != 0


# Phrase: "--key <col>[,<col>...]"
# Context: Usage; key accepts one or more comma-separated column names.
def test_key_accepts_single_column(run, work):
    work.csv("a.csv", ["id", "v"], [["2", "b"], ["1", "a"]])
    r = run("--output", "-", "--key", "id", work.path("a.csv"))
    assert r.ok, r.stderr
    assert body(r) == [["1", "a"], ["2", "b"]]


def test_key_accepts_comma_separated_columns(run, work):
    work.csv("a.csv", ["id", "v"], [["3", "b"], ["3", "a"], ["0", "z"]])
    r = run("--output", "-", "--key", "id,v", work.path("a.csv"))
    assert r.ok, r.stderr
    assert body(r) == [["0", "z"], ["3", "a"], ["3", "b"]]


# Phrase: "[--desc]"  / "[--infer {strict,loose}]" / "[--on-type-error {...}]"
# Context: Usage; optional flags with constrained choices.
def test_optional_flags_are_optional(run, work):
    work.csv("a.csv", ["id"], [["1"]])
    r = run("--output", "-", "--key", "id", work.path("a.csv"))
    assert r.ok, r.stderr


def test_infer_rejects_unknown_choice(run, work):
    work.csv("a.csv", ["id"], [["1"]])
    r = run("--output", "-", "--key", "id", "--infer", "bogus", work.path("a.csv"))
    assert r.returncode != 0


def test_on_type_error_rejects_unknown_choice(run, work):
    work.csv("a.csv", ["id"], [["1"]])
    r = run(
        "--output", "-", "--key", "id", "--on-type-error", "bogus", work.path("a.csv")
    )
    assert r.returncode != 0


def test_infer_accepts_strict_and_loose(run, work):
    work.csv("a.csv", ["id"], [["1"]])
    for mode in ("strict", "loose"):
        r = run("--output", "-", "--key", "id", "--infer", mode, work.path("a.csv"))
        assert r.ok, r.stderr


def test_on_type_error_accepts_all_choices(run, work):
    work.csv("a.csv", ["id"], [["1"]])
    for mode in ("coerce-null", "fail", "keep-string"):
        r = run(
            "--output", "-", "--key", "id", "--on-type-error", mode, work.path("a.csv")
        )
        assert r.ok, r.stderr


# Phrase: "<INPUT1.csv> [<INPUT2.csv> ...]"
# Context: Usage; multiple inputs are merged.
def test_multiple_inputs_are_merged(run, work):
    work.csv("a.csv", ["id"], [["3"], ["1"]])
    work.csv("b.csv", ["id"], [["2"]])
    r = run("--output", "-", "--key", "id", work.path("a.csv"), work.path("b.csv"))
    assert r.ok, r.stderr
    assert body(r) == [["1"], ["2"], ["3"]]


# Phrase: "If `--output -`: write to stdout; otherwise write to file path"
# Context: Output.
def test_output_dash_writes_stdout(run, work):
    work.csv("a.csv", ["id"], [["7"]])
    r = run("--output", "-", "--key", "id", work.path("a.csv"))
    assert r.ok, r.stderr
    assert r.stdout == "id\n7\n"


def test_output_path_writes_file(run, work):
    work.csv("a.csv", ["id"], [["2"], ["1"]])
    out = work.path("merged.csv")
    r = run("--output", out, "--key", "id", work.path("a.csv"))
    assert r.ok, r.stderr
    assert out.read_text(encoding="utf-8") == "id\n1\n2\n"
    assert r.stdout == ""


# Phrase: "--memory-limit-mb <INT>" / "--temp-dir <PATH>"
# Context: Usage; accepted and do not change logical output.
def test_memory_limit_and_temp_dir_accepted(run, work):
    work.csv("a.csv", ["id"], [["2"], ["1"]])
    tmp = work.path("scratch")
    tmp.mkdir()
    r = run(
        "--output", "-", "--key", "id",
        "--memory-limit-mb", "64", "--temp-dir", tmp,
        work.path("a.csv"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["1"], ["2"]]


# Phrase: "Provided schema, composite descending key, ... 128MB memory cap"
# Context: Examples; the documented example invocation must work end to end.
def test_documented_example_invocation(run, work):
    work.schema(
        "schema.json",
        [("id", "int"), ("ts", "timestamp"), ("amount", "float"),
         ("note", "string"), ("is_active", "bool")],
    )
    work.csv(
        "in1.csv",
        ["id", "ts", "amount", "note", "is_active"],
        [["1", "2024-07-01T12:00:00Z", "1.5", "x", "1"]],
    )
    work.csv(
        "in2.csv",
        ["id", "ts", "amount", "note", "is_active"],
        [["2", "2024-07-02T12:00:00Z", "2.5", "y", "0"]],
    )
    r = run(
        "--output", "-", "--key", "ts,id", "--desc",
        "--schema", work.path("schema.json"),
        "--on-type-error", "coerce-null",
        "--memory-limit-mb", "128",
        work.path("in1.csv"), work.path("in2.csv"),
    )
    assert r.ok, r.stderr
    assert header(r) == ["id", "ts", "amount", "note", "is_active"]
    assert [row[0] for row in body(r)] == ["2", "1"]
