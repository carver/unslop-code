"""Spec section: Deliverables / Output Format (CLI surface, framing, fields)."""
import json

from conftest import (CURSOR, complete_at, entry, run_complete, run_raw,
                      write_source)


# --- Phrase: "Write `sith.py` with this interface:
#              python sith.py complete <file> <line> <col> [--fuzzy]"
#     Context: the documented invocation must work.
def test_documented_invocation_succeeds(tmp_path):
    p = write_source(tmp_path, "x = 1\n")
    proc = run_complete(p, 1, 0)
    assert proc.returncode == 0
    json.loads(proc.stdout)


# --- Phrase: "[--fuzzy]"
#     Context: the flag is optional and accepted after the positionals.
def test_fuzzy_flag_accepted(tmp_path):
    p = write_source(tmp_path, "x = 1\n")
    proc = run_complete(p, 1, 0, fuzzy=True)
    assert proc.returncode == 0
    json.loads(proc.stdout)


# --- Phrase: "Output is JSON to STDOUT"
#     Context: STDOUT carries the JSON document.
def test_output_is_json_on_stdout(tmp_path):
    p = write_source(tmp_path, "value = 1\nva\n")
    proc = run_complete(p, 2, 2)
    assert proc.returncode == 0
    json.loads(proc.stdout)


# --- Phrase: "a single JSON object with a `\"completions\"` array"
#     Context: top-level shape.
def test_top_level_shape(tmp_path):
    p = write_source(tmp_path, "value = 1\nva\n")
    data = json.loads(run_complete(p, 2, 2).stdout)
    assert isinstance(data, dict)
    assert list(data.keys()) == ["completions"]
    assert isinstance(data["completions"], list)


# --- Phrase: "Compact format: no extra whitespace."
#     Context: separators must be "," and ":" with no padding.
def test_compact_json_no_extra_whitespace(tmp_path):
    p = write_source(tmp_path, "value = 1\nval\n")
    out = run_complete(p, 2, 3).stdout
    body = out.rstrip("\n")
    assert '", "' not in body and '": "' not in body
    assert ", " not in body and ": " not in body
    assert body == json.dumps(json.loads(body), separators=(",", ":"))


# --- Phrase: "Newline-terminated."
#     Context: exactly one trailing newline, nothing else.
def test_newline_terminated(tmp_path):
    p = write_source(tmp_path, "value = 1\nval\n")
    out = run_complete(p, 2, 3).stdout
    assert out.endswith("\n")
    assert not out.rstrip("\n").endswith("\n")
    assert out.count("\n") == 1


# --- Phrase: "On success, exit 0 (even with zero completions)."
#     Context: a prefix that matches nothing is still a success.
def test_zero_completions_still_exit_zero(tmp_path):
    p = write_source(tmp_path, "zzqqxx_no_such_prefix\n")
    proc = run_complete(p, 1, 21)
    assert proc.returncode == 0
    assert json.loads(proc.stdout) == {"completions": []}


# --- Phrase: "On error, print a message to STDERR and exit 1."
#     Context: errors do not go to stdout.
def test_error_message_on_stderr_exit_1(tmp_path):
    proc = run_complete(tmp_path / "nope.py", 1, 0)
    assert proc.returncode == 1
    assert proc.stderr.strip()
    assert proc.stdout.strip() == ""


# --- Phrase: "Each completion object has: name / complete / type / description"
#     Context: field set of every emitted object.
def test_completion_object_fields(tmp_path):
    data = complete_at(tmp_path, "import os\n\nos\n" + CURSOR)
    for c in data["completions"]:
        assert set(c.keys()) == {"name", "complete", "type", "description"}
        assert all(isinstance(v, str) for v in c.values())


# --- Phrase: "`type` | One of: module, class, function, instance, statement, param, keyword."
#     Context: the closed vocabulary of the type field.
def test_type_vocabulary(tmp_path):
    code = """import os

CONST = 3


def helper(alpha):
    thing = CONST
    """ + CURSOR + """
"""
    data = complete_at(tmp_path, code)
    allowed = {"module", "class", "function", "instance", "statement", "param",
               "keyword"}
    assert {c["type"] for c in data["completions"]} <= allowed


# --- Phrase: "`name` | The full name of the completion."
#     Context: name is the complete identifier, not the remainder.
def test_name_is_full_name(tmp_path):
    data = complete_at(tmp_path, "def alphabet():\n    pass\n\nalph" + CURSOR + "\n")
    assert entry(data, "alphabet")["name"] == "alphabet"


# --- Phrase: "`complete` | ... the name with the already-typed prefix removed."
#     Context: prefix "alph" of "alphabet".
def test_complete_strips_prefix(tmp_path):
    data = complete_at(tmp_path, "def alphabet():\n    pass\n\nalph" + CURSOR + "\n")
    assert entry(data, "alphabet")["complete"] == "abet"


# --- Phrase: "If no prefix, equals `name`."
#     Context: empty prefix.
def test_complete_equals_name_without_prefix(tmp_path):
    data = complete_at(tmp_path, "def alphabet():\n    pass\n\n" + CURSOR + "\n")
    assert entry(data, "alphabet")["complete"] == "alphabet"


# --- Phrase: "When prefix matching is case-insensitive, removal is by character count:
#              the first len(prefix) characters of the matched name are stripped
#              regardless of case."
#     Context: typed "AL", matched name "alphabet".
def test_complete_strips_by_character_count_ignoring_case(tmp_path):
    data = complete_at(tmp_path, "def alphabet():\n    pass\n\nAL" + CURSOR + "\n")
    assert entry(data, "alphabet")["complete"] == "phabet"


# --- Phrase: example output object
#       {"name":"print","complete":"rint","type":"function","description":"def print(...)"}
#     Context: builtin function completion for prefix "p".
def test_example_print_entry(tmp_path):
    data = complete_at(tmp_path, "p" + CURSOR + "\n")
    assert entry(data, "print") == {
        "name": "print", "complete": "rint", "type": "function",
        "description": "def print(...)",
    }


# --- Phrase: example output object
#       {"name":"property","complete":"roperty","type":"class","description":"class property"}
#     Context: builtin class completion for prefix "p".
def test_example_property_entry(tmp_path):
    data = complete_at(tmp_path, "p" + CURSOR + "\n")
    assert entry(data, "property") == {
        "name": "property", "complete": "roperty", "type": "class",
        "description": "class property",
    }


# --- Phrase: "python sith.py complete <file> <line> <col>"
#     Context: argv shape is fixed; malformed invocations are errors (T26).
def test_missing_subcommand_is_error(tmp_path):
    assert run_raw().returncode == 1


def test_unknown_subcommand_is_error(tmp_path):
    p = write_source(tmp_path, "x = 1\n")
    assert run_raw("frobnicate", str(p), 1, 0).returncode == 1


def test_missing_positional_is_error(tmp_path):
    p = write_source(tmp_path, "x = 1\n")
    assert run_raw("complete", str(p), 1).returncode == 1


def test_non_integer_line_is_error(tmp_path):
    p = write_source(tmp_path, "x = 1\n")
    proc = run_raw("complete", str(p), "one", 0)
    assert proc.returncode == 1
    assert proc.stderr.strip()
