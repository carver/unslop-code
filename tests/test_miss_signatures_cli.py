"""bin/miss-signatures: which runs to compare against, and how they are named."""
import json
import sys
import types
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "miss-signatures"
cli = types.ModuleType("miss_signatures_cli")
cli.__file__ = str(SCRIPT)
sys.modules["miss_signatures_cli"] = cli
exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), cli.__dict__)


def fake_run(outputs, prompt, stamp, **problems):
    run = outputs / "spectest" / f"opus-5_2.1.251_high_{prompt}" / stamp
    for problem, message in problems.items():
        evaluation = run / problem / "checkpoint_1" / "evaluation"
        evaluation.mkdir(parents=True)
        (evaluation / "report.json").write_text(json.dumps({"tests": [
            {"nodeid": ".evaluation_tests/test_checkpoint_1.py::test_a", "outcome": "failed",
             "call": {"crash": {"message": message}}}]}))
    return run


def test_other_runs_are_the_rest_of_the_problem_s_runs_named_by_cell_and_time_stamp(tmp_path):
    mine = fake_run(tmp_path, "min13-ABDJKMNT", "20260918T1850", mvvault="assert 1 == 2")
    same = fake_run(tmp_path, "just-solve", "20260915T0940", mvvault="assert 3 == 4")
    elsewhere = fake_run(tmp_path, "just-solve", "20260915T1046", rejector="assert 1 == 2")
    assert cli.other_runs(mine, "mvvault", [mine, same, elsewhere]) == {
        "just-solve v0 opus-5 20260915T0940": {"test_checkpoint_1.py::test_a": "assert N == N"}}


def test_a_run_with_one_problem_needs_no_problem_flag(tmp_path):
    assert cli.the_problem(fake_run(tmp_path, "just-solve", "20260915T0940", mvvault="x"), None) == "mvvault"


def test_a_run_with_several_problems_asks_which(tmp_path):
    run = fake_run(tmp_path, "just-solve", "20260830T0354", mvvault="x", rejector="x")
    with pytest.raises(SystemExit, match="mvvault, rejector"):
        cli.the_problem(run, None)
    assert cli.the_problem(run, "rejector") == "rejector"
