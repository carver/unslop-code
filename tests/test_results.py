"""bin/results: run directories map to (problem, prompt, spec, model) cells."""
import sys
import types
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "results"
rs = types.ModuleType("results"); rs.__file__ = str(SCRIPT); sys.modules["results"] = rs
exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), rs.__dict__)


def test_cell_key_strips_prefix_and_reads_the_spec_from_the_suffix():
    assert rs.cell_key(Path("/o/spectest/opus-5_2.1.251_high_spectest-min4-disambiguated/20260903T1328")) == ("spectest-min4", "patched", "opus-5")
    assert rs.cell_key(Path("/o/dev6-opus5/opus-5_2.1.251_high_just-solve/20260830T0354")) == ("just-solve", "cached", "opus-5")
    assert rs.cell_key(Path("/o/dev6/sonnet-4.6_2.1.44_high_just-solve/20260829T1910")) == ("just-solve", "cached", "sonnet-4.6")


def test_table_averages_a_cell_over_its_runs():
    cells = {("datagate", "spectest-min3", "patched", "opus-5"): [
        {"score": 399/405, "passed": 399, "total": 405, "strict": 5, "ckpts": 7, "cost": 34.0, "erosion": 0.15, "verbosity": 0.16, "ast": 0.06, "cloned": 0.07},
        {"score": 405/405, "passed": 405, "total": 405, "strict": 7, "ckpts": 7, "cost": 30.0, "erosion": 0.11, "verbosity": 0.14, "ast": 0.04, "cloned": 0.05}]}
    row = rs.table(cells).splitlines()[-1]
    assert row.startswith("| datagate | spectest-min3 | patched | opus-5 | 2 | 402.0/405 | 399-405 | 6.0/7 | 32 | 0.130 |")


def test_collect_separates_partial_runs(tmp_path, monkeypatch):
    import json
    run = tmp_path / "spectest" / "opus-5_2.1.251_high_spectest-min3-disambiguated" / "20260903T1057"; run.mkdir(parents=True)
    rows = [{"problem": "datagate", "checkpoint": f"checkpoint_{i}", "idx": i, "passed_tests": 10, "total_tests": 10, "strict_pass_rate": 1.0, "cost": 1.0} for i in (1, 2)]
    (run / "checkpoint_results.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    cells, partial = rs.collect([run], count=lambda problem: 7)
    assert cells == {} and partial[0][:3] == ("datagate", "spectest-min3", "patched") and partial[0][4:6] == (2, 7)
    cells, partial = rs.collect([run], count=lambda problem: 2)
    assert list(cells) == [("datagate", "spectest-min3", "patched", "opus-5")] and partial == []
