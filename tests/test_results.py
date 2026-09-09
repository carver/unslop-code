"""bin/results: run directories map to (problem, prompt, spec, model) cells."""
import sys
import types
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "results"
rs = types.ModuleType("results"); rs.__file__ = str(SCRIPT); sys.modules["results"] = rs
exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), rs.__dict__)


def test_cell_key_strips_prefix_and_falls_back_to_the_suffix_for_the_spec():
    assert rs.cell_key(Path("/o/spectest/opus-5_2.1.251_high_spectest-min4-disambiguated/20260903T1328")) == ("spectest-min4", "v1", "opus-5")
    assert rs.cell_key(Path("/o/spectest/opus-5_2.1.251_high_spectest-v9-specv2/20260906T0000")) == ("spectest-v9", "v0", "opus-5")
    assert rs.cell_key(Path("/o/dev6-opus5/opus-5_2.1.251_high_just-solve/20260830T0354")) == ("just-solve", "v0", "opus-5")
    assert rs.cell_key(Path("/o/dev6/sonnet-4.6_2.1.44_high_just-solve/20260829T1910")) == ("just-solve", "v0", "sonnet-4.6")
    assert rs.cell_key(Path("/o/dev6-fable51/fable-5-1_2.1.251_high_just-solve/20260905T0147")) == ("just-solve", "v0", "fable-5.1")


def test_spec_comes_from_the_catalog_record_when_the_run_has_one(tmp_path):
    import json
    def run(name, record):
        d = tmp_path / name / "20260906T0000"; d.mkdir(parents=True)
        (d / "problem_catalog.json").write_text(json.dumps(record)); return d
    assert rs.spec_of(run("opus-5_2.1.251_high_spectest-v9-specv2", {"version": "env-override", "commit": "/x/specs/v2/problems"})) == "v2"
    assert rs.spec_of(run("opus-5_2.1.251_high_min12-specv1", {"version": "env-override", "commit": "/x/specs/xjq/v1/problems"})) == "v1"
    assert rs.spec_of(run("opus-5_2.1.251_high_spectest-v9-disambiguated", {"version": "env-override", "commit": "/x/problems"})) == "v1"
    assert rs.spec_of(run("opus-5_2.1.251_high_just-solve", {"version": "v1.0", "commit": "4d38d3"})) == "v0"


def test_table_averages_a_cell_over_its_runs():
    cells = {("datagate", "spectest-min3", "v1", "opus-5"): [
        {"score": 399/405, "passed": 399, "total": 405, "strict": 5, "ckpts": 7, "cost": 34.0, "minutes": 120.0, "erosion": 0.15, "verbosity": 0.16, "ast": 0.06, "cloned": 0.07},
        {"score": 405/405, "passed": 405, "total": 405, "strict": 7, "ckpts": 7, "cost": 30.0, "minutes": 140.0, "erosion": 0.11, "verbosity": 0.14, "ast": 0.04, "cloned": 0.05}]}
    row = rs.table(cells).splitlines()[-1]
    assert row.startswith("| datagate | spectest-min3 | v1 | opus-5 | 2 | 402.0/405 | 399-405 | 6.0/7 | 5-7 | 32 | 130 | 0.130 |")


def test_collect_separates_partial_runs(tmp_path, monkeypatch):
    import json
    run = tmp_path / "spectest" / "opus-5_2.1.251_high_spectest-min3-disambiguated" / "20260903T1057"; run.mkdir(parents=True)
    rows = [{"problem": "datagate", "checkpoint": f"checkpoint_{i}", "idx": i, "passed_tests": 10, "total_tests": 10, "strict_pass_rate": 1.0, "cost": 1.0} for i in (1, 2)]
    (run / "checkpoint_results.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    cells, partial = rs.collect([run], checkpoints=lambda problem, run: {f"checkpoint_{i}" for i in range(1, 8)})
    assert cells == {} and partial[0][:3] == ("datagate", "spectest-min3", "v1") and partial[0][4:6] == (2, 7)
    cells, partial = rs.collect([run], checkpoints=lambda problem, run: {"checkpoint_1", "checkpoint_2"})
    assert list(cells) == [("datagate", "spectest-min3", "v1", "opus-5")] and partial == []


def test_collect_uses_the_catalog_record_and_requires_each_checkpoint(tmp_path, monkeypatch):
    import json
    catalog = tmp_path / "catalog"
    problem_dir = catalog / "datagate"; problem_dir.mkdir(parents=True)
    for i in range(1, 4):
        (problem_dir / f"checkpoint_{i}.md").write_text("")
    run = tmp_path / "spectest" / "opus-5_2.1.251_high_test" / "20260909T0000"; run.mkdir(parents=True)
    (run / "problem_catalog.json").write_text(json.dumps({"version": "env-override", "commit": str(catalog)}))
    rows = [
        {"problem": "datagate", "checkpoint": "checkpoint_1", "idx": 1, "passed_tests": 10, "total_tests": 10},
        {"problem": "datagate", "checkpoint": "checkpoint_1", "idx": 1, "passed_tests": 10, "total_tests": 10},
        {"problem": "datagate", "checkpoint": "checkpoint_3", "idx": 3, "passed_tests": 10, "total_tests": 10},
    ]
    (run / "checkpoint_results.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    cells, partial = rs.collect([run])
    assert cells == {}
    assert partial[0][4:6] == (2, 3)


def test_single_run_score_has_no_decimal():
    cells = {("datagate", "spectest-min4", "v1", "opus-5"): [
        {"score": 1.0, "passed": 405, "total": 405, "strict": 7, "ckpts": 7, "cost": 43.0, "minutes": 210.0, "erosion": 0.17, "verbosity": 0.16, "ast": 0.08, "cloned": 0.07}]}
    assert "| 1 | 405/405 | - | 7/7 | - |" in rs.table(cells).splitlines()[-1]


def test_agreeing_runs_show_no_decimal_and_no_range():
    assert rs.counted([399, 399], 405) == ("399/405", "-")
    assert rs.counted([5, 5, 5], 7) == ("5/7", "-")
    assert rs.counted([397, 400], 405) == ("398.5/405", "397-400")


def test_tied_cells_sort_by_prompt_name_without_the_spectest_prefix():
    run = {"score": 1.0, "passed": 405, "total": 405, "strict": 7, "ckpts": 7, "cost": 30.0, "minutes": 140.0, "erosion": 0.1, "verbosity": 0.1, "ast": 0.1, "cloned": 0.1}
    cells = {("datagate", "min4-ABCHJK", "v1", "opus-5"): [run], ("datagate", "spectest-min4", "v1", "opus-5"): [run]}
    prompts = [line.split(" | ")[1] for line in rs.table(cells).splitlines()[2:]]
    assert prompts == ["spectest-min4", "min4-ABCHJK"]
