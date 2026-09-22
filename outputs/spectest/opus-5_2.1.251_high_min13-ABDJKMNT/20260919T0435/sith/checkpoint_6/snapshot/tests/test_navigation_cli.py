"""The shape, exit codes and argument handling of `infer` and `goto`."""

import json

from conftest import run_cli


# Spec: "python sith.py infer <file> <line> <col>" / "Output is a JSON object with a
#        `definitions` array."
def test_infer_returns_a_definitions_object(infer):
    result = infer("class Calculator:\n    pass\nc = Calc|ulator\n")
    assert list(json.loads(result.stdout)) == ["definitions"]
    assert isinstance(result.definitions, list)


# Spec: "python sith.py goto <file> <line> <col>"
def test_goto_returns_a_definitions_object(goto):
    result = goto("class Calculator:\n    pass\nc = Calc|ulator\n")
    assert list(json.loads(result.stdout)) == ["definitions"]


# Spec: "If the cursor is not on a name, exit 1." (infer)
def test_infer_off_a_name_exits_one(infer):
    result = infer("value = 1\n     |\n", expect_ok=False)
    assert result.returncode == 1


# Spec: "If the cursor is not on a name, exit 1." (goto)
def test_goto_off_a_name_exits_one(goto):
    result = goto("value = 1\n     |\n", expect_ok=False)
    assert result.returncode == 1


# Spec: "If the name cannot be resolved, return an empty array (exit 0)."
def test_unresolvable_name_is_an_empty_array(infer):
    result = infer("no_such_name_at_all|\n")
    assert result.definitions == []
    assert result.returncode == 0


# Spec: "If no definition is found, return an empty array (exit 0)." (goto)
def test_goto_without_a_definition_is_an_empty_array(goto):
    result = goto("no_such_name_at_all|\n")
    assert result.definitions == []
    assert result.returncode == 0


# Spec: the output is a single JSON object per invocation.
def test_output_is_one_compact_json_line(infer):
    result = infer("x = 1\n|x\n")
    assert result.stdout.count("\n") == 1
    assert ", " not in result.stdout


# Spec: both subcommands take <file> <line> <col>; a missing file is an error.
def test_missing_file_exits_one(workdir):
    result = run_cli("infer", str(workdir / "absent.py"), 1, 0, cwd=workdir)
    assert result.returncode == 1
    assert result.stdout == ""


def test_out_of_range_position_exits_one(infer):
    assert infer("x = 1\n", line=40, col=0, expect_ok=False).returncode == 1
