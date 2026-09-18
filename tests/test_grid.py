"""bin/grid: the two-prompt, two-spec uplift grid from bin/results cells."""
import sys
import types
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "grid"
gr = types.ModuleType("grid")
gr.__file__ = str(SCRIPT)
sys.modules["grid"] = gr
exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), gr.__dict__)


def run(score, erosion, cost=10.0, minutes=30.0, by_ckpt=None):
    return {"score": score, "passed": 0, "total": 0, "strict": 0, "ckpts": 1, "cost": cost, "minutes": minutes,
            "erosion": erosion, "erosion_by_ckpt": by_ckpt or [erosion], "verbosity": 0.2, "ast": 0.1, "cloned": 0.05}


CELLS = {
    ("xjq", "just-solve", "v0", "opus-5"): [
        run(0.9, 0.4, by_ckpt=[0.1, 0.3, 0.5, 0.7]),
        run(0.8, 0.6, by_ckpt=[0.3, 0.5, 0.7, 0.9, 1.1]),
    ],
    ("xjq", "min12-ABDJKMN", "v0", "opus-5"): [run(0.9, 0.1, by_ckpt=[0.1, None, 0.1])],
    ("xjq", "min12-ABDJKMN", "v3", "opus-5"): [run(1.0, 0.05)],
    ("xjq", "just-solve", "v3", "opus-5"): [run(1.0, 0.5)],
    ("xjq", "just-solve", "v2", "opus-5"): [run(0.95, 0.5)],
    ("sith", "just-solve", "v0", "opus-5"): [run(0.5, 0.7)],
    ("sith", "min12-ABDJKMN", "v0", "opus-5"): [run(0.7, 0.3)],
    ("sith", "min12-ABDJKMN", "v1", "opus-5"): [run(0.9, 0.3)],  # no just-solve v1: not a patched cell
    ("xjq", "just-solve", "v0", "fable-5.1"): [run(0.1, 0.9)],  # other model, ignored
    ("xjq", "min11-ABDFJKMN", "v0", "opus-5"): [run(0.1, 0.9)],  # other prompt, ignored
}


def test_fail_is_the_share_of_hidden_tests_failed_and_minutes_come_through():
    figures = gr.run_figures(run(0.9, 0.4, minutes=42.0))
    assert abs(figures["fail"] - 0.1) < 1e-9
    assert figures["minutes"] == 42.0


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
    assert lines[0].startswith(
        "| problem | patched | just-solve v0 | min12-ABDJKMN v0 | min12-ABDJKMN patched | just-solve patched |"
    )
    assert lines[2].startswith(
        "| sith | - | 50.0% / 0.70 / 0.10 / $10 / 30m (1) | 30.0% / 0.30 / 0.10 / $10 / 30m (1) | - | - |"
    )
    assert lines[3].startswith("| xjq | v3 | 15.0% / 0.50 / 0.10 / $10 / 30m (2) |")
    assert lines[-1].startswith("| mean | n=1/2 | 32.5% / 0.60 / 0.10 / $10 / 30m (2) |")


def test_phases_pin_the_ends_and_split_the_interior_into_thirds_by_position():
    def names(count):
        return [gr.PHASES[gr.phase_of(i, count)] for i in range(count)]

    assert names(3) == ["Start", "Mid", "Final"]
    assert names(4) == ["Start", "Early", "Late", "Final"]
    assert names(5) == ["Start", "Early", "Mid", "Late", "Final"]
    assert names(7) == ["Start", "Early", "Early", "Mid", "Late", "Late", "Final"]
    assert names(8) == ["Start", "Early", "Early", "Mid", "Mid", "Late", "Late", "Final"]


def test_trajectory_pools_each_prompts_v0_checkpoints_by_phase():
    t = gr.grid(CELLS)["trajectory"]
    assert t["spec"] == "v0" and t["phases"] == ["Start", "Early", "Mid", "Late", "Final"]
    js = t["prompts"]["just-solve"]
    assert js["runs"] == 3  # xjq's two and sith's one
    assert js["ckpts"] == [3, 2, 1, 2, 2]  # sith's single checkpoint is Start only
    assert abs(js["erosion"][0] - (0.1 + 0.3 + 0.7) / 3) < 1e-9  # Start: xjq 0.1, xjq 0.3, sith 0.7
    assert abs(js["erosion"][2] - 0.7) < 1e-9  # Mid: only the five-checkpoint run's middle
    assert abs(js["erosion"][4] - (0.7 + 1.1) / 2) < 1e-9
    m = t["prompts"]["min12-ABDJKMN"]
    assert (
        m["ckpts"] == [2, 0, 0, 0, 1] and m["erosion"][2] is None
    )  # the None checkpoint is skipped, an empty phase is null


REPOS = [
    {"name": "flask", "all": {"erosion": 0.2, "ast": 0.05}, "impl": {"erosion": 0.3, "ast": 0.10}},
    {"name": "salt", "all": {"erosion": 0.6, "ast": 0.15}, "impl": {"erosion": 0.7, "ast": 0.30}},
    {"name": "django", "all": {"erosion": 0.3, "ast": 0.04}, "impl": {"erosion": 0.5, "ast": 0.12}},
    {"name": "tqdm", "all": {"erosion": 0.5, "ast": 0.10}, "impl": {"erosion": 0.6, "ast": 0.18}},
    {"name": "click", "all": {"erosion": 0.4, "ast": 0.06}, "impl": {"erosion": 0.4, "ast": 0.11}},
]


def test_human_panel_gives_the_mean_the_named_extremes_and_the_quartiles_of_one_part():
    erosion = gr.human_panel(REPOS, "all")["erosion"]
    assert erosion["n"] == 5 and abs(erosion["mean"] - 0.4) < 1e-9
    assert erosion["min"] == {"repo": "flask", "value": 0.2} and erosion["max"] == {"repo": "salt", "value": 0.6}
    assert abs(erosion["q1"] - 0.3) < 1e-9 and abs(erosion["q3"] - 0.5) < 1e-9
    assert gr.human_panel(REPOS, "impl")["ast"]["max"] == {"repo": "salt", "value": 0.30}


def test_relative_puts_every_human_figure_on_the_share_scale():
    human = gr.grid(CELLS, human=gr.human_panel(REPOS, "all"))["relative"]["metrics"]["erosion"]["human"]
    per_unit = (1 / 0.5 + 1 / 0.7) / 2  # a value's share: its mean over the problems of value / just-solve
    assert abs(human["mean"] - 0.4 * per_unit) < 1e-9 and human["value"] == 0.4 and human["n"] == 5
    assert human["min"]["repo"] == "flask" and abs(human["min"]["share"] - 0.2 * per_unit) < 1e-9
    assert abs(human["max"]["share"] - 0.6 * per_unit) < 1e-9
    assert abs(human["q1"]["share"] - 0.3 * per_unit) < 1e-9 and abs(human["q3"]["share"] - 0.5 * per_unit) < 1e-9


def test_impl_run_swaps_in_the_implementation_only_scores_checkpoint_by_checkpoint():
    counts = {"a/snapshot": {"total_loc": 100, "ast_grep_flagged_loc": 30, "clone_loc": 10, "high_cc_mass": 2.0,
                             "total_mass": 10.0},
              "b/snapshot": {"total_loc": 100, "ast_grep_flagged_loc": 10, "clone_loc": 0, "high_cc_mass": 6.0,
                             "total_mass": 10.0}}
    whole = run(0.9, 0.05) | {"snapshots": ["a/snapshot", "b/snapshot"]}
    out = gr.impl_run(whole, split=lambda snapshot: {"impl": counts[snapshot]})
    assert out["erosion_by_ckpt"] == [0.2, 0.6] and abs(out["erosion"] - 0.4) < 1e-9
    assert abs(out["ast"] - 0.2) < 1e-9 and abs(out["cloned"] - 0.05) < 1e-9
    assert out["verbosity"] is None  # not split, so not passed off as implementation-only
    assert out["score"] == 0.9 and out["cost"] == whole["cost"]


def test_impl_cells_keeps_only_the_cells_the_grid_draws():
    seen = []

    def split(snapshot):
        seen.append(snapshot)
        return {"impl": {"total_loc": 10, "ast_grep_flagged_loc": 1, "clone_loc": 0, "high_cc_mass": 1.0,
                         "total_mass": 4.0}}

    cells = {key: [r | {"snapshots": [f"{key[0]}-{key[1]}-{key[2]}"]} for r in runs] for key, runs in CELLS.items()}
    out = gr.impl_cells(cells, split=split)
    assert ("xjq", "just-solve", "v0", "fable-5.1") not in out  # another model
    assert ("xjq", "just-solve", "v2", "opus-5") not in out  # neither v0 nor the patched spec
    assert ("sith", "min12-ABDJKMN", "v1", "opus-5") not in out  # no just-solve v1, so not a patched cell
    assert ("xjq", "min12-ABDJKMN", "v3", "opus-5") in out and "xjq-just-solve-v2" not in seen
    assert out[("sith", "just-solve", "v0", "opus-5")][0]["erosion"] == 0.25


def test_relative_averages_each_problems_share_of_the_first_prompt_and_names_the_extremes():
    r = gr.grid(CELLS)["relative"]
    assert r["spec"] == "v0" and r["baseline"] == "just-solve"
    erosion = r["metrics"]["erosion"]
    assert erosion["n"] == 2
    assert abs(erosion["prompt"]["mean"] - (0.1 / 0.5 + 0.3 / 0.7) / 2) < 1e-9  # not 0.2 / 0.6, the share of the means
    assert erosion["prompt"]["best"] == {"problem": "xjq", "share": 0.1 / 0.5}
    assert erosion["prompt"]["worst"] == {"problem": "sith", "share": 0.3 / 0.7}
    assert "human" not in erosion  # no panel given
    assert abs(r["metrics"]["ast"]["prompt"]["mean"] - 1.0) < 1e-9


def test_relative_skips_a_problem_whose_baseline_is_zero_or_whose_other_prompt_never_ran():
    cells = dict(CELLS)
    cells[("clean", "just-solve", "v0", "opus-5")] = [run(0.9, 0.0)]
    cells[("clean", "min12-ABDJKMN", "v0", "opus-5")] = [run(0.9, 0.2)]
    cells[("half", "just-solve", "v0", "opus-5")] = [run(0.9, 0.5)]
    erosion = gr.grid(cells)["relative"]["metrics"]["erosion"]
    assert erosion["n"] == 2
    assert {erosion["prompt"]["best"]["problem"], erosion["prompt"]["worst"]["problem"]} == {"xjq", "sith"}


def test_problem_set_reads_a_split_by_name_and_all_means_no_filter():
    assert gr.problem_set("dev") == {"datagate", "file_merger", "mvvault", "rejector", "sith", "xjq"}
    assert len(gr.problem_set("test")) == 15
    assert gr.problem_set("all") is None


def test_only_keeps_the_named_problems_cells():
    kept = gr.only(CELLS, {"sith"})
    assert kept and {key[0] for key in kept} == {"sith"}
    assert gr.only(CELLS, None) == CELLS
