"""Spec: Clarifications shared by the refactoring subcommands."""

import json


# Spec: "changed_files | object" and "renames | object" are the answer of a
# refactoring, as one compact newline-terminated JSON object.
def test_json_answer_holds_both_sections(rename):
    result = rename("def hel$per():\n    pass\n", "worker")
    assert list(json.loads(result.stdout)) == ["changed_files", "renames"]
    assert result.stdout.endswith("}\n")
    assert ", " not in result.stdout


# Spec: "For --diff, stdout is unified diff text only (no JSON envelope)."
def test_diff_is_unified_diff_text_only(rename):
    result = rename("def hel$per():\n    pass\n\nhelper()\n", "worker", diff=True)
    lines = result.stdout.splitlines()
    assert lines[0].startswith("--- ")
    assert lines[1].startswith("+++ ")
    assert lines[2].startswith("@@")


# Spec: "All refactoring commands that accept --diff (rename, inline,
# extract-variable, extract-function) use the same plain-text unified diff
# format."
def test_inline_diff_uses_the_same_format(inline):
    result = inline("val$ue = 3\nprint(value)\n", diff=True)
    assert result.stdout.splitlines()[0].startswith("--- ")


# Spec: "... use the same plain-text unified diff format."
def test_extract_function_diff_uses_the_same_format(extract_function):
    result = extract_function("def outer():\n    a = 1\n$    print(a)~\n", "report", diff=True)
    assert result.stdout.splitlines()[0].startswith("--- ")


# Spec: "Map of file path (relative to project root)" - the root is the one
# --project names.
def test_project_option_sets_the_paths_in_the_answer(rename):
    extra = {"pack/library.py": "def helper():\n    pass\n"}
    result = rename(
        "def hel$per():\n    pass\n", "worker",
        name="pack/module_under_test.py", extra=extra, project=".",
    )
    assert list(result.changed_files) == ["pack/module_under_test.py"]


# Spec: "Validation failures (invalid name, cursor not on name, invalid
# selection) exit 1 and must not emit partial edit output."
def test_every_validation_failure_is_silent_on_stdout(rename, inline, extract_variable):
    assert rename("def hel$per():\n    pass\n", "class").stdout == ""
    assert inline("def hel$per():\n    pass\n").stdout == ""
    assert extract_variable("result = $compute(3~) + 1\n", "value").stdout == ""
