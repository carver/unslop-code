"""bin/ast-rules: one column per run of bin/quality-split's snapshots."""
import sys
import types
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "ast-rules"
ar = types.ModuleType("ast_rules")
ar.__file__ = str(SCRIPT)
sys.modules["ast_rules"] = ar
exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), ar.__dict__)


def found(problem, prompt, stamp):
    run = Path("outputs/spectest") / f"opus-5_2.1.251_high_{prompt}" / stamp
    return problem, prompt, run, run / problem / "checkpoint_6" / "snapshot"


def test_columns_of_one_problem_are_named_by_prompt_and_time_stamp():
    rows = [found("mvvault", "min12-ABDJKMN", "20260914T2119"), found("mvvault", "min13-ABDJKMNT", "20260918T1850")]
    assert ar.run_names(rows) == ["min12-ABDJKMN 20260914T2119", "min13-ABDJKMNT 20260918T1850"]


def test_columns_of_several_problems_lead_with_the_problem():
    rows = [found("mvvault", "just-solve", "20260915T0940"), found("rejector", "just-solve", "20260915T1046")]
    assert ar.run_names(rows) == ["mvvault just-solve 20260915T0940", "rejector just-solve 20260915T1046"]
