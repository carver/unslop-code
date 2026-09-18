"""bin/fork-run: a copy of a run keeps the early checkpoints and reads a later spec version."""
import json
import sys
import types
from pathlib import Path

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "fork-run"
mod = types.ModuleType("fork_run"); mod.__file__ = str(SCRIPT); sys.modules["fork_run"] = mod
exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), mod.__dict__)


def make_run(root, family="opus-5_high_min12-specv4", stamp="20260910T1126", checkpoints=(1, 2, 3, 4), evaluated=None):
    run = root / "outputs" / "spectest" / family / stamp
    evaluated = checkpoints if evaluated is None else evaluated
    for n in checkpoints:
        ck = run / "file_merger" / f"checkpoint_{n}"
        (ck / "snapshot").mkdir(parents=True)
        if n in evaluated:
            (ck / "evaluation.json").write_text("{}")
    (run / "config.yaml").write_text(
        f"output_path: {run}\nproblems:\n  - file_merger\nsave_template: spectest/{family}/{stamp}\n")
    (run / "problem_catalog.json").write_text(json.dumps({"version": "env-override", "commit": f"{root}/specs/file_merger/v4/problems"}))
    (run / "checkpoint_results.jsonl").write_text("".join(
        json.dumps({"problem": "file_merger", "checkpoint": f"checkpoint_{n}", "path": f"{run}/file_merger/checkpoint_{n}"}) + "\n"
        for n in checkpoints))
    (run / "file_merger" / "run_info.yaml").write_text(yaml.safe_dump(
        {"seed": 42, "summary": {"checkpoints": {f"checkpoint_{n}": "ran" for n in checkpoints}, "total_cost": 20.0}}, sort_keys=False))
    (root / "specs" / "file_merger" / "v5" / "problems" / "file_merger").mkdir(parents=True)
    mod.ROOT = root
    return run


def test_fork_keeps_early_checkpoints_and_points_everything_at_the_new_spec(tmp_path):
    run = make_run(tmp_path)
    dst = mod.fork(run, "v5", 2)
    assert dst == tmp_path / "outputs" / "spectest" / "opus-5_high_min12-specv5" / "20260910T1126"
    assert sorted(p.name for p in (dst / "file_merger").glob("checkpoint_*")) == ["checkpoint_1", "checkpoint_2"]
    assert sorted(p.name for p in (run / "file_merger").glob("checkpoint_*")) == [f"checkpoint_{n}" for n in (1, 2, 3, 4)]
    config = (dst / "config.yaml").read_text()
    assert f"output_path: {dst}" in config and "save_template: spectest/opus-5_high_min12-specv5/20260910T1126" in config
    assert "specv4" not in config
    assert json.loads((dst / "problem_catalog.json").read_text()) == {
        "version": "env-override", "commit": str(tmp_path / "specs" / "file_merger" / "v5" / "problems")}
    rows = [json.loads(line) for line in (dst / "checkpoint_results.jsonl").read_text().splitlines()]
    assert [r["checkpoint"] for r in rows] == ["checkpoint_1", "checkpoint_2"]
    assert all(r["path"].startswith(str(dst)) for r in rows)
    info = yaml.safe_load((dst / "file_merger" / "run_info.yaml").read_text())
    assert info["summary"]["checkpoints"] == {"checkpoint_1": "ran", "checkpoint_2": "ran"}
    assert info["seed"] == 42 and info["summary"]["total_cost"] == 20.0


def test_a_run_without_a_spec_suffix_gets_one(tmp_path):
    run = make_run(tmp_path, family="opus-5_high_min12")
    assert mod.fork(run, "v5", 1).parent.name == "opus-5_high_min12-specv5"


def test_refuses_an_existing_destination(tmp_path):
    run = make_run(tmp_path)
    mod.fork(run, "v5", 2)
    with pytest.raises(SystemExit, match="exists"):
        mod.fork(run, "v5", 2)


def test_refuses_a_keep_beyond_the_finished_checkpoints(tmp_path):
    run = make_run(tmp_path, evaluated=(1, 2))
    with pytest.raises(SystemExit, match="finished: \\[1, 2\\]"):
        mod.fork(run, "v5", 3)
    with pytest.raises(SystemExit, match="not a finished"):
        mod.fork(run, "v5", 0)


def test_refuses_v0_and_an_unbuilt_spec(tmp_path):
    run = make_run(tmp_path)
    with pytest.raises(SystemExit, match="patched version"):
        mod.fork(run, "v0", 2)
    with pytest.raises(SystemExit, match="bin/spec-patch file_merger v6"):
        mod.fork(run, "v6", 2)


def test_main_prints_the_copy_and_the_resume_command(tmp_path, capsys):
    run = make_run(tmp_path)
    mod.main([str(run), "--spec", "v5", "--keep", "2"])
    out = capsys.readouterr().out.splitlines()
    assert out[0].endswith("opus-5_high_min12-specv5/20260910T1126")
    assert out[1] == f"continue with: {mod.HERE / 'queue'} resume-strict {out[0]}"
