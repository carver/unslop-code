"""Spec section: Determinism Checklist — exact exit codes and stderr shape."""

from conftest import rows_of


# Phrase: "Exact exit codes and stderr message shape as specified"
# Context: Determinism Checklist. Success is code 0 with an empty stderr.
def test_success_is_zero_with_no_stderr(csv_file, run_tool):
    csv_file("a.csv", "id\n1\n")
    result = run_tool("--output", "-", "--key", "id", "a.csv")
    assert result.returncode == 0
    assert result.stderr == ""


# Phrase: "Exact exit codes and stderr message shape as specified"
# Context: Determinism Checklist. Ambiguity T22: one prefixed line per failure.
def test_error_messages_are_prefixed_with_the_program_name(jsonl_file, run_tool):
    jsonl_file("a.jsonl", [{"id": 1}])
    result = run_tool("--output", "-", "--key", "nope", "a.jsonl")
    assert result.stderr.startswith("merge_files.py: error: ")
    assert result.stderr.endswith("\n")
    assert result.stdout == ""


# Phrase: "otherwise error 2"
# Context: New Input Types. Ambiguity T21: 2 also covers command-line misuse.
def test_command_line_misuse_is_error_2(csv_file, run_tool):
    csv_file("a.csv", "id\n1\n")
    result = run_tool("--output", "-", "a.csv")
    assert result.returncode == 2


# Phrase: "On cast failure, follow --on-type-error from checkpoint 1"
# Context: Casting. Ambiguity T21: `fail` has its own exit code.
def test_cast_failure_under_fail_has_its_own_code(csv_file, run_tool):
    csv_file("a.csv", "id,v\n1,abc\n")
    csv_file(
        "schema.json",
        '{"columns": [{"name": "id", "type": "int"}, {"name": "v", "type": "int"}]}',
    )
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json",
        "--on-type-error", "fail", "a.csv",
    )
    assert result.returncode == 4
    assert result.stderr


# Phrase: "Exact exit codes"
# Context: Determinism Checklist. Ambiguity T21: an unreadable input is code 1.
def test_unreadable_input_is_error_1(run_tool):
    result = run_tool("--output", "-", "--key", "id", "absent.csv")
    assert result.returncode == 1
    assert result.stderr


# Phrase: "If --schema provided, it defines exact output columns, types, and order"
# Context: Schema Resolution. Ambiguity T21: a broken schema file is a schema error.
def test_unusable_schema_file_is_error_3(csv_file, run_tool):
    csv_file("a.csv", "id\n1\n")
    csv_file("schema.json", '{"columns": [{"name": "id", "type": "decimal"}]}')
    result = run_tool(
        "--output", "-", "--key", "id", "--schema", "schema.json", "a.csv"
    )
    assert result.returncode == 3
    assert result.stderr


# Phrase: "Flat-only enforcement for JSONL/Parquet; nested structures trigger error 6"
# Context: Determinism Checklist. The two formats share the code.
def test_nested_inputs_share_error_6(jsonl_file, parquet_file, run_tool):
    jsonl_file("a.jsonl", [{"id": 1, "meta": {"k": 1}}])
    parquet_file("b.parquet", {"id": [1], "meta": [{"k": 1}]})
    from_jsonl = run_tool("--output", "-", "--key", "id", "a.jsonl")
    from_parquet = run_tool("--output", "-", "--key", "id", "b.parquet")
    assert from_jsonl.returncode == 6
    assert from_parquet.returncode == 6


# Phrase: "--output - writes to stdout; otherwise write atomically"
# Context: Output. A run that fails leaves no partial output file behind.
def test_failed_run_leaves_no_output_file(csv_file, run_tool, workdir):
    csv_file("a.csv", "id,v\n1,1\n2,abc\n")
    csv_file(
        "schema.json",
        '{"columns": [{"name": "id", "type": "int"}, {"name": "v", "type": "int"}]}',
    )
    result = run_tool(
        "--output", "out.csv", "--key", "id", "--schema", "schema.json",
        "--on-type-error", "fail", "a.csv",
    )
    assert result.returncode == 4
    assert not (workdir / "out.csv").exists()


# Phrase: "otherwise write atomically"
# Context: Output. A successful run replaces the destination and leaves no scratch files.
def test_atomic_write_replaces_the_destination(csv_file, run_tool, workdir):
    csv_file("a.csv", "id\n7\n")
    csv_file("out.csv", "stale content\n")
    result = run_tool("--output", "out.csv", "--key", "id", "a.csv")
    assert result.returncode == 0, result.stderr
    assert (workdir / "out.csv").read_text(encoding="utf-8") == "id\n7\n"
    assert sorted(path.name for path in workdir.iterdir()) == ["a.csv", "out.csv"]


# Phrase: "All rows from all inputs appear exactly once"
# Context: Output. An error in a later input aborts the whole run.
def test_a_broken_later_input_aborts_the_run(csv_file, jsonl_file, run_tool):
    csv_file("a.csv", "id\n1\n")
    jsonl_file("b.jsonl", '{"id": 2}\nnot json\n')
    result = run_tool("--output", "-", "--key", "id", "a.csv", "b.jsonl")
    assert result.returncode == 5
    assert rows_of(result.stdout) == []
