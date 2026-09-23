"""Miss collection for bin/compare-runs."""
import json
import sys
import types
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "compare-runs"
cr = types.ModuleType("compare_runs")
cr.__file__ = str(SCRIPT)
sys.modules["compare_runs"] = cr
exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), cr.__dict__)


def test_misses_dedupe_a_test_across_the_checkpoints_it_fails_at(tmp_path):
    (tmp_path / "checkpoint_1").mkdir()
    (tmp_path / "checkpoint_2").mkdir()
    (tmp_path / "checkpoint_1" / "evaluation.json").write_text(
        json.dumps({"tests": {"checkpoint_1-Functionality": {"failed": ["TestA::t_ws"]}}})
    )
    (tmp_path / "checkpoint_2" / "evaluation.json").write_text(
        json.dumps(
            {
                "tests": {
                    "checkpoint_1-Regression": {"failed": ["TestA::t_ws"]},
                    "checkpoint_2-Core": {"failed": ["TestB::t_rowid"], "passed": ["TestB::ok"]},
                }
            }
        )
    )
    assert cr.misses(tmp_path) == {(1, "TestA::t_ws"), (2, "TestB::t_rowid")}


def test_run_label_drops_the_shared_model_prefix():
    assert (
        cr.run_label(Path("/o/spectest/opus-5_2.1.251_high_spectest-v8A-disambiguated/20260902T2341"))
        == "spectest-v8A-disambiguated/20260902T2341"
    )
    assert (
        cr.run_label(Path("/o/spectest/opus-5-5_2.1.280_high_min13-ABDJKMNT-specv1/20260923T1200"))
        == "opus-5-5 min13-ABDJKMNT-specv1/20260923T1200"
    )


def test_parse_args_keeps_the_problem_value_out_of_the_run_list():
    runs, problem, md, _ = cr.parse_args(["--problem", "datagate", "outputs/a", "--md", "outputs/b"])
    assert [r.name for r in runs] == ["a", "b"]
    assert (problem, md) == ("datagate", True)


def test_parse_args_defaults():
    assert cr.parse_args(["outputs/a"])[1:] == (None, False, False)


def test_parse_args_takes_succinct():
    runs, problem, md, succinct = cr.parse_args(["a", "--succinct"])
    assert [r.name for r in runs] == ["a"] and succinct and not md
