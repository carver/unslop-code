"""bin/miss-report: each failing test with its source, its failure output and the registry entries near it."""
import json
import sys
import types
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "miss-report"
mr = types.ModuleType("miss_report")
mr.__file__ = str(SCRIPT)
sys.modules["miss_report"] = mr
exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), mr.__dict__)

TEST_FILE = '''\
import pytest


class TestLimits:
    def test_other(self):
        assert True

    @pytest.mark.parametrize("budget", [100, 200])
    def test_tpm_gate(self, budget):
        """A request waits until the token window frees room for its reservation."""
        elapsed = run(budget)
        assert elapsed >= 1.0


def test_report_shape():
    assert report()["rows"] == 3
'''

# The test's name shares a word with T1 (gate) and with T2 (tpm); its docstring and output settle it for T2.
REGISTRY = """## T1. Whether evaluation gates the solutions greedy collects
### Choice
It does.
### Risk: 20
Maybe not.

## T2. When a waiting request wakes after the TPM token window frees room
### Choice
On the next tick.
### Risk: 30
On the exact expiry.

## T3. Rounding of the report's totals
### Choice
Two decimals.
### Risk: 10
None.
"""

STDOUT = """\
=================================== FAILURES ===================================
_____________________ TestLimits.test_tpm_gate[100] ______________________
>       assert elapsed >= 1.0
E       assert 0.2 >= 1.0
E        +  the reservation never waited
=========================== short test summary info ============================
"""


def make_run(tmp_path, family="opus-5_high_min13-ABDJKMNT-specv1", registry=REGISTRY, failed=("test_tpm_gate[100]",)):
    problems = tmp_path / "specs" / "rejector" / "v1" / "problems"
    (problems / "rejector" / "tests").mkdir(parents=True)
    (problems / "rejector" / "tests" / "test_checkpoint_1.py").write_text(TEST_FILE)
    (problems / "rejector" / "checkpoint_1.md").write_text("# Limits\nThe tpm gate holds a request.\n")
    run = tmp_path / "outputs" / "spectest" / family / "20260920T2113"
    checkpoint = run / "rejector" / "checkpoint_1"
    (checkpoint / "snapshot").mkdir(parents=True)
    (checkpoint / "evaluation").mkdir()
    if registry:
        (checkpoint / "snapshot" / "AMBIGUITIES.md").write_text(registry)
    (checkpoint / "evaluation" / "stdout.txt").write_text(STDOUT)
    (checkpoint / "evaluation.json").write_text(
        json.dumps({"tests": {"checkpoint_1-Core": {"passed": ["test_other"], "failed": list(failed)}}})
    )
    return run


def test_a_test_failing_at_several_checkpoints_is_one_miss(tmp_path):
    for n, failed in ((1, ["TestCore::test_a"]), (2, ["TestCore::test_a", "TestX::test_b[xls]"])):
        checkpoint = tmp_path / "prob" / f"checkpoint_{n}"
        checkpoint.mkdir(parents=True)
        evaluation = {"tests": {"checkpoint_1-Regression": {"failed": failed}}}
        (checkpoint / "evaluation.json").write_text(json.dumps(evaluation))
    assert mr.failing_tests(tmp_path, "prob") == {(1, "test_a"): [1, 2], (1, "test_b[xls]"): [2]}


def test_a_patched_run_reads_the_tests_of_its_own_spec_version(tmp_path):
    run = make_run(tmp_path)
    default = tmp_path / "cache"
    assert mr.problem_root(run, "rejector", tmp_path / "specs", default) == tmp_path / "specs/rejector/v1/problems"
    unpatched = run.parent.parent / "opus-5_high_min13-ABDJKMNT" / "20260920T2113"
    assert mr.problem_root(unpatched, "rejector", tmp_path / "specs", default) == default
    no_such_version = run.parent.parent / "opus-5_high_min13-ABDJKMNT-specv9" / "20260920T2113"
    assert mr.problem_root(no_such_version, "rejector", tmp_path / "specs", default) == default


def test_test_source_finds_a_parametrized_method_and_stops_at_the_next_test(tmp_path):
    make_run(tmp_path)
    root = tmp_path / "specs/rejector/v1/problems"
    doc, keep = mr.test_source(root, "rejector", 1, "test_tpm_gate[100]")
    assert doc == "A request waits until the token window frees room for its reservation."
    assert keep == ['@pytest.mark.parametrize("budget", [100, 200])', "assert elapsed >= 1.0"]


def test_a_missing_test_file_is_reported_not_raised(tmp_path):
    doc, keep = mr.test_source(tmp_path, "rejector", 7, "test_x")
    assert "test_checkpoint_7.py" in doc and keep == []


def test_failure_lines_are_the_e_lines_of_the_tests_own_section(tmp_path):
    run = make_run(tmp_path)
    assert mr.failure_lines(run, "rejector", 1, "test_tpm_gate[100]") == [
        "E       assert 0.2 >= 1.0",
        "E        +  the reservation never waited",
    ]
    assert mr.failure_lines(run, "rejector", 1, "test_tpm") == []  # a prefix of another test's name is not it
    assert mr.failure_lines(run, "rejector", 3, "test_tpm_gate[100]") == []  # no such checkpoint


def test_brief_ranks_by_the_tests_source_and_output_not_only_its_name(tmp_path, capsys):
    run = make_run(tmp_path)
    mr.main([str(run), "--brief", "--specs", str(tmp_path / "specs")])
    assert capsys.readouterr().out.splitlines() == [
        "1 failing test, 3 registry entries; candidates by shared words, read them before citing",
        "test_tpm_gate[100]",
        "   30  T2. When a waiting request wakes after the TPM token window frees room"
        "  [tpm, frees, request, room, token, window]",
        "   20  T1. Whether evaluation gates the solutions greedy collects  [gate]",
    ]


def test_brief_folds_the_cases_of_one_test(tmp_path, capsys):
    run = make_run(tmp_path, failed=("test_tpm_gate[100]", "test_tpm_gate[200]"))
    mr.main([str(run), "--brief", "--specs", str(tmp_path / "specs")])
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("2 failing tests, 3 registry entries")
    assert out[1] == "test_tpm_gate[100] (+1 more case)"
    assert len(out) == 4


def test_brief_on_a_run_without_a_registry_says_so(tmp_path, capsys):
    run = make_run(tmp_path, registry=None)
    mr.main([str(run), "--brief", "--specs", str(tmp_path / "specs")])
    assert capsys.readouterr().out.splitlines() == ["1 failing test; this run kept no registry (AMBIGUITIES.md)"]


def test_brief_on_a_clean_run(tmp_path, capsys):
    run = make_run(tmp_path, failed=())
    mr.main([str(run), "--brief", "--specs", str(tmp_path / "specs")])
    assert capsys.readouterr().out.splitlines() == ["no failing tests in this run"]


def test_the_full_report_carries_the_failure_output_and_the_shared_words(tmp_path, capsys):
    run = make_run(tmp_path)
    mr.main([str(run), "--specs", str(tmp_path / "specs")])
    out = capsys.readouterr().out
    assert "## checkpoint 1: `test_tpm_gate[100]`" in out
    assert "> A request waits until the token window frees room for its reservation." in out
    assert "E       assert 0.2 >= 1.0" in out
    assert "2: The tpm gate holds a request." in out
    assert "- T2. When a waiting request wakes after the TPM token window frees room (Risk 30) [tpm, frees," in out
    assert out.index("- T2. ") < out.index("- T1. ")
