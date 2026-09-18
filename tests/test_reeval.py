"""bin/reeval: installing a fresh evaluation into a checkpoint keeps the old one and rebuilds its row."""
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "bin" / "reeval"
mod = types.ModuleType("reeval")
mod.__file__ = str(SCRIPT)
sys.modules["reeval"] = mod
exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), mod.__dict__)
if not mod.harness_available():  # the row rewrite needs the harness: run these under bin/scb's venv
    pytest.skip("slop_code is not importable here; run with ~/.venvs/scbench-harness/bin/python", allow_module_level=True)


def make_run(tmp_path):
    run = tmp_path / "run"
    ck = run / "mvvault" / "checkpoint_6"
    (ck / "evaluation").mkdir(parents=True)
    (ck / "evaluation.json").write_text(json.dumps({"pass_counts": {"Core": 5}, "total_counts": {"Core": 5}}))
    (ck / "evaluation" / "report.json").write_text("old")
    rows = [{"problem": "mvvault", "checkpoint": "checkpoint_5", "strict_pass_rate": 0.9, "cost": 1.0},
            {"problem": "mvvault", "checkpoint": "checkpoint_6", "strict_pass_rate": 1.0, "total_tests": 42, "passed_tests": 42,
             "regression_total": 0, "regression_passed": 0, "cost": 2.5},
            {"problem": "xjq", "checkpoint": "checkpoint_6", "strict_pass_rate": 1.0, "cost": 3.0}]
    (run / "checkpoint_results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    fresh = tmp_path / "fresh"
    (fresh / "evaluation").mkdir(parents=True)
    (fresh / "evaluation.json").write_text(json.dumps({"pass_counts": {"Core": 5, "Regression": 179}, "total_counts": {"Core": 5, "Regression": 185}}))
    (fresh / "evaluation" / "report.json").write_text("new")
    return run, fresh


def test_install_backs_up_and_rewrites_only_that_row(tmp_path):
    run, fresh = make_run(tmp_path)
    mod.install(run, "mvvault", "checkpoint_6", fresh, tag="prior-tests")
    ck = run / "mvvault" / "checkpoint_6"
    assert json.loads((ck / "evaluation.json").read_text())["total_counts"]["Regression"] == 185
    assert json.loads((ck / "evaluation.json.before-prior-tests").read_text())["total_counts"] == {"Core": 5}
    assert (ck / "evaluation" / "report.json").read_text() == "new"
    assert (ck / "evaluation.before-prior-tests" / "report.json").read_text() == "old"
    rows = [json.loads(line) for line in (run / "checkpoint_results.jsonl").read_text().splitlines()]
    assert rows[0]["strict_pass_rate"] == 0.9 and rows[2]["strict_pass_rate"] == 1.0
    six = rows[1]
    assert six["total_tests"] == 190 and six["passed_tests"] == 184 and six["regression_total"] == 185
    assert abs(six["strict_pass_rate"] - 184 / 190) < 1e-9 and six["isolated_pass_rate"] == 1.0
    assert six["cost"] == 2.5


def test_install_refuses_a_second_time_without_a_new_tag(tmp_path):
    run, fresh = make_run(tmp_path)
    mod.install(run, "mvvault", "checkpoint_6", fresh, tag="prior-tests")
    try:
        mod.install(run, "mvvault", "checkpoint_6", fresh, tag="prior-tests")
    except SystemExit as e:
        assert "before-prior-tests" in str(e)
    else:
        raise AssertionError("a second install overwrote the backup")
