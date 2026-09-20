"""bin/run-recap: the sibling runs a recap compares against."""
import sys
import types
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "run-recap"
rr = types.ModuleType("run_recap")
rr.__file__ = str(SCRIPT)
sys.modules["run_recap"] = rr
exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), rr.__dict__)


def summary(run):
    return {"snapshots": [f"/o/{run}/xjq/checkpoint_1/snapshot", f"/o/{run}/xjq/checkpoint_2/snapshot"]}


CELLS = {
    ("xjq", "min12-ABDJKMN", "v0", "opus-5"): [summary("min12/b"), summary("min12/a")],
    ("xjq", "just-solve", "v0", "opus-5"): [summary("js/a")],
    ("xjq", "min13-ABDJKMNT", "v0", "opus-5"): [summary("min13/a")],
    ("xjq", "just-solve", "v3", "opus-5"): [summary("js-v3/a")],  # other spec
    ("sith", "just-solve", "v0", "opus-5"): [summary("js/sith")],  # other problem
    ("xjq", "just-solve", "v0", "fable-5.1"): [summary("js/fable")],  # other model
}


def test_siblings_are_the_same_problem_spec_and_model_in_prompt_order_without_the_run_itself():
    out = rr.siblings(CELLS, "xjq", "v0", "opus-5", "/o/min13/a")
    assert out == [Path("/o/js/a"), Path("/o/min12/a"), Path("/o/min12/b")]


def test_prompts_at_lists_the_prompts_that_ran_the_cell_in_order():
    assert rr.prompts_at(CELLS, "xjq", "v0", "opus-5") == ["just-solve", "min12-ABDJKMN", "min13-ABDJKMNT"]
    assert rr.prompts_at(CELLS, "xjq", "v3", "opus-5") == ["just-solve"]
