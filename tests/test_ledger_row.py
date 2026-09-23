"""bin/ledger-row: misses keyed by origin checkpoint, with the checkpoints they failed at."""
import json
import sys
import types
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "ledger-row"
lr = types.ModuleType("ledger_row")
lr.__file__ = str(SCRIPT)
sys.modules["ledger_row"] = lr
exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), lr.__dict__)


def test_failures_track_origin_and_every_checkpoint_failed_at(tmp_path):
    (tmp_path / "checkpoint_1").mkdir()
    (tmp_path / "checkpoint_2").mkdir()
    (tmp_path / "checkpoint_1" / "evaluation.json").write_text(
        json.dumps({"tests": {"checkpoint_1-Core": {"failed": ["T::a"]}}})
    )
    (tmp_path / "checkpoint_2" / "evaluation.json").write_text(
        json.dumps(
            {"tests": {"checkpoint_1-Regression": {"failed": ["T::a"]}, "checkpoint_2-Core": {"failed": ["T::b"]}}}
        )
    )
    assert lr.failures(tmp_path) == {(1, "T::a"): [1, 2], (2, "T::b"): [2]}


def counts(loc, ast=0, clone=0, high=0.0, mass=0.0):
    return {"total_loc": loc, "ast_grep_flagged_loc": ast, "clone_loc": clone, "high_cc_mass": high, "total_mass": mass,
            "verbosity_flagged_loc": max(ast, clone)}


def test_the_quality_clause_is_the_checkpoint_mean_then_the_final_implementation_alone():
    rows = [{"erosion": 0.0, "verbosity": 0.1, "ast_grep_pct": 0.04, "cloned_pct": 0.06},
            {"erosion": 0.2, "verbosity": 0.3, "ast_grep_pct": 0.08, "cloned_pct": 0.10}]
    split = {"impl": counts(1000, ast=132, clone=14, high=9.0, mass=250.0), "test": counts(3000), "all": counts(4000)}
    assert lr.quality_clause(rows, split) == (
        "Quality: erosion 0.100, verbosity 0.200, ast 0.060, cloned 0.080; "
        "final checkpoint, implementation only (25% of LOC): ast 0.132, erosion 0.036, cloned 0.014")


def test_the_quality_clause_skips_checkpoints_without_scores_and_a_run_with_no_implementation():
    rows = [{"erosion": None}, {"erosion": 0.2, "verbosity": 0.3, "ast_grep_pct": 0.08, "cloned_pct": 0.10}]
    split = {"impl": counts(0), "test": counts(0), "all": counts(0)}
    assert lr.quality_clause(rows, split) == (
        "Quality: erosion 0.200, verbosity 0.300, ast 0.080, cloned 0.100; "
        "final checkpoint, implementation only (- of LOC): ast -, erosion -, cloned -")


def test_a_run_on_another_model_keeps_the_model_in_its_row_and_heading(tmp_path, monkeypatch, capsys):
    run = tmp_path / "opus-5-5_2.1.280_high_min13-ABDJKMNT-specv1" / "20260923T1200"
    row = {"problem": "rejector", "checkpoint": "checkpoint_1", "idx": 1, "passed_tests": 5, "total_tests": 5,
           "strict_pass_rate": 1.0, "cost": 2.0, "elapsed": 600, "ended": "2026-09-23T13:00:00"}
    monkeypatch.setattr(lr.summarize, "load_rows", lambda _: [row])
    monkeypatch.setattr(lr.scb_split, "split_reports", lambda _: None)
    monkeypatch.setattr(lr, "quality_clause", lambda rows, split: "QUALITY")
    monkeypatch.setattr(sys, "argv", ["ledger-row", str(run)])
    lr.main()
    out = capsys.readouterr().out
    assert out.startswith(
        "| opus-5-5 min13-ABDJKMNT-specv1 | `…opus-5-5_2.1.280_high_min13-ABDJKMNT-specv1/20260923T1200` |"
    )
    assert "### opus-5-5 min13-ABDJKMNT-specv1\n" in out
