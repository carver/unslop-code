"""CLI surface, JSON envelope and exit codes."""
import json

from conftest import run_cli


# Spec: "python sith.py complete <file> <line> <col> [--fuzzy]"
def test_complete_subcommand_accepts_file_line_col(complete):
    result = complete("x = 1\n|\n")
    assert result.returncode == 0


# Spec: "Output is JSON to STDOUT - a single JSON object with a `\"completions\"` array."
def test_stdout_is_object_with_completions_array(complete):
    payload = complete("x = 1\n|\n").payload
    assert isinstance(payload, dict)
    assert list(payload) == ["completions"]
    assert isinstance(payload["completions"], list)


# Spec: "Compact format: no extra whitespace."
def test_output_is_compact_json(complete):
    stdout = complete("x = 1\nx|\n").stdout
    assert stdout.rstrip("\n") == json.dumps(json.loads(stdout), separators=(",", ":"))
    assert ", " not in stdout
    assert '": ' not in stdout


# Spec: "Newline-terminated."
def test_output_ends_with_single_newline(complete):
    stdout = complete("x = 1\nx|\n").stdout
    assert stdout.endswith("\n")
    assert not stdout[:-1].endswith("\n")


# Spec: "On success, exit 0 (even with zero completions)."
def test_zero_completions_still_exits_zero(complete):
    result = complete("zzz_no_such_prefix_qqq|\n")
    assert result.returncode == 0
    assert result.completions == []
    assert result.stdout == '{"completions":[]}\n'


# Spec: "On error, print a message to STDERR and exit 1."
def test_error_writes_message_to_stderr_and_exits_one(workdir):
    result = run_cli("complete", str(workdir / "missing.py"), 1, 0)
    assert result.returncode == 1
    assert result.stderr.strip() != ""
    assert result.stdout == ""


# Spec: "Each completion object has: name / complete / type / description"
def test_completion_object_field_set(complete):
    completion = complete("def alpha():\n    pass\nalph|\n").by_name("alpha")
    assert set(completion) == {"name", "complete", "type", "description"}
    assert all(isinstance(v, str) for v in completion.values())


# Spec: type is "One of: module, class, function, instance, statement, param, keyword."
def test_type_field_is_from_the_allowed_set(complete):
    allowed = {"module", "class", "function", "instance", "statement", "param", "keyword"}
    source = (
        "import os\n\n\nclass C:\n    pass\n\n\n"
        "def f(p):\n    v = 1\n    unknown = os.getcwd()\n    |\n"
    )
    for completion in complete(source).completions:
        assert completion["type"] in allowed
