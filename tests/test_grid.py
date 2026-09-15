"""bin/grid: the two-prompt, two-spec uplift grid from bin/results cells."""
import sys
import types
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "grid"
gr = types.ModuleType("grid"); gr.__file__ = str(SCRIPT); sys.modules["grid"] = gr
exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), gr.__dict__)


def run(score, erosion, cost=10.0):
    return {"score": score, "passed": 0, "total": 0, "strict": 0, "ckpts": 1, "cost": cost, "minutes": 1.0,
            "erosion": erosion, "verbosity": 0.2, "ast": 0.1, "cloned": 0.05}


CELLS = {
    ("xjq", "just-solve", "v0", "opus-5"): [run(0.9, 0.4), run(0.8, 0.6)],
    ("xjq", "min12-ABDJKMN", "v0", "opus-5"): [run(0.9, 0.1)],
    ("xjq", "min12-ABDJKMN", "v3", "opus-5"): [run(1.0, 0.05)],
    ("xjq", "just-solve", "v3", "opus-5"): [run(1.0, 0.5)],
    ("xjq", "just-solve", "v2", "opus-5"): [run(0.95, 0.5)],
    ("sith", "just-solve", "v0", "opus-5"): [run(0.5, 0.7)],
    ("sith", "min12-ABDJKMN", "v0", "opus-5"): [run(0.7, 0.3)],
    ("sith", "min12-ABDJKMN", "v1", "opus-5"): [run(0.9, 0.3)],  # no just-solve v1: not a patched cell
    ("xjq", "just-solve", "v0", "fable-5.1"): [run(0.1, 0.9)],  # other model, ignored
    ("xjq", "min11-ABDFJKMN", "v0", "opus-5"): [run(0.1, 0.9)],  # other prompt, ignored
}


def test_fail_is_the_share_of_hidden_tests_failed():
    assert abs(gr.run_figures(run(0.9, 0.4))["fail"] - 0.1) < 1e-9


def test_patched_spec_is_the_highest_version_both_prompts_have():
    assert gr.patched_spec(CELLS, "xjq", gr.DEFAULT_PROMPTS, "opus-5") == "v3"
    assert gr.patched_spec(CELLS, "sith", gr.DEFAULT_PROMPTS, "opus-5") is None


def test_grid_cells_average_their_runs_and_means_average_the_problems():
    g = gr.grid(CELLS)
    xjq = g["problems"]["xjq"]
    assert xjq["patched"] == "v3"
    assert abs(xjq["cells"]["just-solve|v0"]["mean"]["fail"] - 0.15) < 1e-9
    assert abs(xjq["cells"]["just-solve|v0"]["mean"]["erosion"] - 0.5) < 1e-9
    assert len(xjq["cells"]["just-solve|v0"]["runs"]) == 2
    assert "just-solve|patched" not in g["problems"]["sith"]["cells"]
    assert g["means"]["just-solve|v0"]["n"] == 2
    assert abs(g["means"]["just-solve|v0"]["fail"] - (0.15 + 0.5) / 2) < 1e-9
    assert g["means"]["min12-ABDJKMN|patched"]["n"] == 1


def test_table_has_a_row_per_problem_and_a_mean_row():
    lines = gr.table(gr.grid(CELLS)).splitlines()
    assert lines[0].startswith("| problem | patched | just-solve v0 | min12-ABDJKMN v0 | min12-ABDJKMN patched | just-solve patched |")
    assert lines[2].startswith("| sith | - | 50.0% / 0.70 / 0.10 (1) | 30.0% / 0.30 / 0.10 (1) | - | - |")
    assert lines[3].startswith("| xjq | v3 | 15.0% / 0.50 / 0.10 (2) |")
    assert lines[-1].startswith("| mean | n=1/2 | 32.5% / 0.60 / 0.10 (2) |")
