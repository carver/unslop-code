"""bin/test-history: one test's pass, fail or not-reached in each run of a problem, oldest first."""
import json
import sys
import types
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "test-history"
mod = types.ModuleType("test_history")
mod.__file__ = str(SCRIPT)
sys.modules["test_history"] = mod
exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), mod.__dict__)


def evaluation(passed, failed):
    return json.dumps({"tests": {"checkpoint_4-Error": {"passed": passed, "failed": failed}}})


def make_outputs(tmp_path):
    outputs = tmp_path / "outputs"
    older = outputs / "spectest" / "opus-5_2.1.251_high_min12" / "20260909T0739" / "file_merger" / "checkpoint_4"
    newer = outputs / "spectest" / "opus-5_2.1.251_high_min12-specv3" / "20260910T0934" / "file_merger" / "checkpoint_4"
    short = outputs / "spectest" / "opus-5_2.1.251_high_min12-specv1" / "20260909T1429" / "file_merger" / "checkpoint_1"
    for d in (older, newer, short):
        d.mkdir(parents=True)
    (older / "evaluation.json").write_text(evaluation(["test_error_cases[errors/alias_cycle]"], []))
    (newer / "evaluation.json").write_text(evaluation([], ["test_error_cases[errors/alias_cycle]"]))
    (short / "evaluation.json").write_text(evaluation(["test_core_cases[x]"], []))
    return outputs


def test_history_orders_runs_by_time_and_marks_unreached(tmp_path):
    rows = mod.history("file_merger", "alias_cycle", make_outputs(tmp_path))
    assert [label.split("/")[1] for label, _, _ in rows] == ["20260909T0739", "20260909T1429", "20260910T0934"]
    states = [hits.get("test_error_cases[errors/alias_cycle]", "-") for _, _, hits in rows]
    assert states == ["pass", "-", "FAIL"]


def test_main_prints_a_tally_and_one_line_per_run(tmp_path, capsys):
    mod.main(["file_merger", "alias_cycle", "--outputs", str(make_outputs(tmp_path))])
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "test_error_cases[errors/alias_cycle]: 1 pass, 1 fail, 1 not reached"
    assert [line.split()[0] for line in out[1:]] == ["pass", "-", "FAIL"]


def test_succinct_groups_runs_by_state_and_drops_the_version_and_effort(tmp_path, capsys):
    mod.main(["file_merger", "alias_cycle", "--outputs", str(make_outputs(tmp_path)), "--succinct"])
    assert capsys.readouterr().out.splitlines() == [
        "test_error_cases[errors/alias_cycle]: 1 pass, 1 fail, 1 not reached",
        "  FAIL: opus-5 min12-specv3/20260910T0934",
        "  pass: opus-5 min12/20260909T0739",
        "  -: opus-5 min12-specv1/20260909T1429",
    ]


def test_short_label_drops_only_the_version_and_effort_segment():
    assert mod.short_label("opus-5_2.1.251_high_min12-ABDJKMN/2026") == "opus-5 min12-ABDJKMN/2026"
    assert mod.short_label("sonnet-4.6_2.1.44_high_just-solve/2026") == "sonnet-4.6 just-solve/2026"
    assert mod.short_label("odd/20260829T1910") == "odd/20260829T1910"
