"""bin/quality-split: scb-check scores of implementation files against test files."""
import json
import sys
import types
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "quality-split"
qs = types.ModuleType("quality_split")
qs.__file__ = str(SCRIPT)
sys.modules["quality_split"] = qs
exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), qs.__dict__)


def report(loc, ast=0, clone=0, high=0.0, mass=0.0, verbose=None):
    return {"total_loc": loc, "ast_grep_flagged_loc": ast, "clone_loc": clone, "high_cc_mass": high, "total_mass": mass,
            "verbosity_flagged_loc": verbose if verbose is not None else max(ast, clone)}


def tree(tmp_path, *names):
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x = 1\n")
    return tmp_path


def seen_by_checker(tmp_path, part, *names):
    seen = []

    def check(directory):
        seen.extend(sorted(str(p.relative_to(directory)) for p in Path(directory).rglob("*.py")))
        return report(len(seen))

    qs.part_report(tree(tmp_path, *names), part, check)
    return seen


NAMES = ("app.py", "pkg/core.py", "tests/test_app.py", "conftest.py", ".venv/lib/x.py", "pkg/__pycache__/y.py")


def test_the_implementation_tree_has_no_test_files_or_environments(tmp_path):
    assert seen_by_checker(tmp_path, "impl", *NAMES) == ["app.py", "pkg/core.py"]


def test_the_test_tree_has_only_test_files(tmp_path):
    assert seen_by_checker(tmp_path, "test", *NAMES) == ["conftest.py", "tests/test_app.py"]


def test_a_part_with_no_files_scores_zero_without_running_the_checker(tmp_path):
    def check(_):
        raise AssertionError("checker ran on an empty tree")

    assert qs.part_report(tree(tmp_path, "app.py"), "test", check) == report(0)


def test_split_reports_are_cached(tmp_path):
    calls = []

    def check(directory):
        calls.append(directory)
        return report(10, ast=2)

    source = tree(tmp_path / "src", "app.py", "test_app.py")
    first = qs.split_reports(source, tmp_path / "cache", check)
    assert qs.split_reports(str(source), tmp_path / "cache", check) == first  # a path given as text is the same tree
    assert len(calls) == 3
    assert first["impl"]["ast_grep_flagged_loc"] == 2


def test_a_cached_split_missing_a_count_is_recomputed(tmp_path):
    source = tree(tmp_path / "src", "app.py", "test_app.py")
    stale = {part: {k: v for k, v in report(10, ast=2).items() if k != "verbosity_flagged_loc"} for part in qs.PARTS}
    qs.split_reports(source, tmp_path / "cache", lambda d: report(1))  # fills the cache
    for f in (tmp_path / "cache").glob("*.json"):
        f.write_text(json.dumps(stale))
    fresh = qs.split_reports(source, tmp_path / "cache", lambda d: report(10, ast=2, verbose=4))
    assert fresh["impl"]["verbosity_flagged_loc"] == 4


def test_pooled_sums_the_runs_before_dividing():
    a = {"impl": report(100, ast=30, high=5.0, mass=10.0), "test": report(0), "all": report(100, ast=30)}
    b = {"impl": report(300, ast=50, clone=40, high=1.0, mass=10.0), "test": report(400, ast=20),
         "all": report(700, ast=70)}
    row = qs.pooled([a, b])
    assert row["runs"] == 2
    assert row["impl"] == {"loc": 400, "ast_lines": 80, "ast": 0.2, "cloned": 0.1, "verbosity": 0.2, "erosion": 0.3}
    assert row["test"]["ast"] == 0.05
    assert row["all"]["ast"] == 0.125
    assert row["test_share"] == 0.5


def test_a_part_with_no_lines_has_no_scores():
    a = {"impl": report(100, ast=30), "test": report(0), "all": report(100, ast=30)}
    assert qs.pooled([a])["test"]["ast"] is None


def test_a_tree_with_no_python_prints_dashes():
    empty = dict.fromkeys(("impl", "test", "all"), report(0))
    line = qs.table([{"name": "rusty", **qs.pooled([empty])}]).splitlines()[-1]
    assert line == "| rusty | - | 1 | 0 | 0 | - | - / - / - | - / - / - | - / - / - | - / - / - |"


def fake_run(outputs, prompt, stamp, problem, scored, model="opus-5"):
    run = outputs / "spectest" / f"{model}_2.1.251_high_{prompt}" / stamp
    for n in range(1, 4):
        (run / problem / f"checkpoint_{n}" / "snapshot").mkdir(parents=True)
    for n in scored:
        analysis = run / problem / f"checkpoint_{n}" / "quality_analysis"
        analysis.mkdir()
        (analysis / "scb_check.json").write_text("{}")
    (run / "checkpoint_results.jsonl").write_text("")
    return run


def test_final_snapshots_are_the_last_scored_checkpoint_of_each_matching_run(tmp_path):
    first = fake_run(tmp_path, "min13-ABDJKMNT", "20260918T1850", "mvvault", scored=(1, 2))
    fake_run(tmp_path, "min13-ABDJKMNT", "20260918T2129", "rejector", scored=(1,))
    fake_run(tmp_path, "just-solve", "20260915T0940", "mvvault", scored=(1, 2, 3))
    fake_run(tmp_path, "min13-ABDJKMNT", "20260919T0100", "mvvault", scored=())
    fake_run(tmp_path, "min13-ABDJKMNT", "20260919T0200", "mvvault", scored=(1,), model="sonnet-4.6")
    found = list(qs.final_snapshots(["min13-ABDJKMNT"], "opus-5", {"mvvault"}, qs.results.run_dirs(tmp_path)))
    assert found == [("mvvault", "min13-ABDJKMNT", first, first / "mvvault" / "checkpoint_2" / "snapshot")]


def test_final_snapshots_take_a_named_checkpoint_and_skip_runs_that_never_reached_it(tmp_path):
    first = fake_run(tmp_path, "min13-ABDJKMNT", "20260918T1850", "mvvault", scored=(1, 2, 3))
    fake_run(tmp_path, "min13-ABDJKMNT", "20260919T0100", "mvvault", scored=())
    runs = qs.results.run_dirs(tmp_path)
    found = list(qs.final_snapshots(["min13-ABDJKMNT"], "opus-5", None, runs, checkpoint=1))
    assert found == [("mvvault", "min13-ABDJKMNT", first, first / "mvvault" / "checkpoint_1" / "snapshot")]
