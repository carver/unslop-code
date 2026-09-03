"""Checkpoint selection and window-guard tests for bin/scb-extend."""
import datetime
import yaml
import json
import subprocess
import sys
import types
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "scb-extend"
ext = types.ModuleType("scb_extend")
ext.__file__ = str(SCRIPT)
sys.modules["scb_extend"] = ext
exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), ext.__dict__)

UTC = datetime.timezone.utc


def reading(pct, resets_at="2026-09-02T21:20:00+00:00"):
    return {"five_hour": {"pct": pct, "resets_at": resets_at}}


def rec(n, phase, pct, resets_at="2026-09-02T21:20:00+00:00"):
    return {"checkpoint": n, "phase": phase, **reading(pct, resets_at)}


def make_problem(tmp_path, evaluated, partial=()):
    for n in evaluated:
        d = tmp_path / f"checkpoint_{n}"; d.mkdir()
        (d / "evaluation.json").write_text(json.dumps({"pass_counts": {"Core": 4, "Error": 1}, "total_counts": {"Core": 5, "Error": 1}, "infrastructure_failure": False}))
        (d / "inference_result.json").write_text(json.dumps({"had_error": False})); (d / "snapshot").mkdir()
    for n in partial:
        (tmp_path / f"checkpoint_{n}").mkdir()
    return tmp_path


def test_next_checkpoint_is_first_without_evaluation(tmp_path):
    p = make_problem(tmp_path, evaluated=[1, 2], partial=[3])
    assert ext.next_checkpoint(p, 7) == 3


def test_next_checkpoint_none_when_all_evaluated(tmp_path):
    p = make_problem(tmp_path, evaluated=[1, 2])
    assert ext.next_checkpoint(p, 2) is None


def test_outcome_sums_pass_and_total_counts(tmp_path):
    p = make_problem(tmp_path, evaluated=[1])
    assert ext.outcome(p, 1) == (5, 6, False)
    assert ext.outcome(p, 2) is None


def test_window_costs_pair_readings_within_one_window():
    records = [rec(1, "before", 20), rec(1, "after", 45),
               rec(2, "before", 45), rec(2, "after", 5, resets_at="2026-09-03T02:20:00+00:00"),
               rec(3, "before", 5, resets_at="2026-09-03T02:20:00+00:00"), rec(3, "after", 22, resets_at="2026-09-03T02:20:00+00:00")]
    assert ext.window_costs(records) == [25, 17]


def test_reserve_defaults_then_tracks_largest_cost():
    assert ext.reserve([]) == ext.DEFAULT_RESERVE
    assert ext.reserve([rec(1, "before", 20), rec(1, "after", 40)]) == 25.0


def test_no_wait_when_reserve_fits():
    now = datetime.datetime(2026, 9, 2, 20, 0, tzinfo=UTC)
    assert ext.seconds_until_room(reading(60), 40, now) == 0


def test_wait_runs_until_reset_plus_slack():
    now = datetime.datetime(2026, 9, 2, 21, 0, tzinfo=UTC)
    assert ext.seconds_until_room(reading(75), 30, now) == 20 * 60 + ext.RESET_SLACK_S


def test_wait_is_only_slack_when_reset_already_passed():
    now = datetime.datetime(2026, 9, 2, 22, 0, tzinfo=UTC)
    assert ext.seconds_until_room(reading(75), 30, now) == ext.RESET_SLACK_S


def finished_checkpoint(problem_dir, n, had_error=False):
    d = problem_dir / f"checkpoint_{n}"; d.mkdir(parents=True, exist_ok=True)
    (d / "evaluation.json").write_text("{}"); (d / "inference_result.json").write_text(json.dumps({"had_error": had_error})); (d / "snapshot").mkdir()


def write_run_info(problem_dir, states):
    (problem_dir / "run_info.yaml").write_text(yaml.safe_dump({"seed": 42, "summary": {"checkpoints": states, "state": "error"}}))


def test_repair_marks_finished_checkpoints_ran_and_keeps_a_backup(tmp_path):
    finished_checkpoint(tmp_path, 1); finished_checkpoint(tmp_path, 2); (tmp_path / "checkpoint_3").mkdir()
    write_run_info(tmp_path, {"checkpoint_1": "skipped", "checkpoint_2": "skipped", "checkpoint_3": "error"})
    now = datetime.datetime(2026, 9, 2, 21, 0, 0, tzinfo=UTC)
    assert ext.repair_run_info(tmp_path, 7, now) == ["checkpoint_1", "checkpoint_2"]
    info = yaml.safe_load((tmp_path / "run_info.yaml").read_text())
    assert info["summary"]["checkpoints"] == {"checkpoint_1": "ran", "checkpoint_2": "ran", "checkpoint_3": "error"}
    assert info["seed"] == 42 and info["summary"]["state"] == "error"
    backup = yaml.safe_load((tmp_path / "run_info.yaml.bak-20260902T210000").read_text())
    assert backup["summary"]["checkpoints"]["checkpoint_1"] == "skipped"


def test_repair_leaves_a_consistent_run_info_alone(tmp_path):
    finished_checkpoint(tmp_path, 1)
    write_run_info(tmp_path, {"checkpoint_1": "ran", "checkpoint_2": "skipped"})
    before = (tmp_path / "run_info.yaml").read_text()
    assert ext.repair_run_info(tmp_path, 7) == []
    assert (tmp_path / "run_info.yaml").read_text() == before
    assert not list(tmp_path.glob("run_info.yaml.bak-*"))


def test_repair_without_run_info_is_a_noop(tmp_path):
    finished_checkpoint(tmp_path, 1)
    assert ext.repair_run_info(tmp_path, 7) == []


PREVIEW = """Resume preview for /runs/x
datagate:
  Resume from: checkpoint_1
  Completed: 
  Would delete and re-run:
    - checkpoint_1 (missing results)
    - checkpoint_2 (depends on invalid checkpoint)
  Directories to delete:
    - /runs/x/datagate/checkpoint_1
    - /runs/x/datagate/checkpoint_2

No changes made (dry run).
"""


def test_deletions_lists_the_directories_a_preview_would_remove():
    assert ext.deletions(PREVIEW) == [Path("/runs/x/datagate/checkpoint_1"), Path("/runs/x/datagate/checkpoint_2")]


def test_deletions_empty_when_preview_keeps_everything():
    assert ext.deletions("datagate:\n  Resume from: checkpoint_3\n  Completed: checkpoint_1, checkpoint_2\n\nNo changes made (dry run).\n") == []


def test_finished_dir_needs_evaluation_result_and_snapshot(tmp_path):
    finished_checkpoint(tmp_path, 1); (tmp_path / "checkpoint_2").mkdir(); (tmp_path / "checkpoint_2" / "prompt.txt").write_text("x")
    assert ext.finished_dir(tmp_path / "checkpoint_1")
    assert not ext.finished_dir(tmp_path / "checkpoint_2")


def test_output_dir_parsed_through_ansi_colour():
    assert ext.output_dir_from("\x1b[32m\x1b[1mOutput directory: /runs/x/20260902T2100\x1b[0m\n") == Path("/runs/x/20260902T2100")
    assert ext.output_dir_from("Starting run...\n") is None


def test_backup_tars_each_finished_checkpoint_once(tmp_path, monkeypatch):
    run_dir = tmp_path / "spectest-v4" / "20260902T2100"; problem_dir = run_dir / "datagate"
    finished_checkpoint(problem_dir, 1); (problem_dir / "checkpoint_2").mkdir()
    write_run_info(problem_dir, {"checkpoint_1": "ran"})
    monkeypatch.setattr(ext, "backup_dir", lambda: tmp_path / "backups")
    assert ext.backup_finished(run_dir, "datagate", 7) == ["checkpoint_1"]
    tgz = tmp_path / "backups" / "spectest-v4-20260902T2100-checkpoint_1.tgz"
    assert tgz.exists()
    assert ext.backup_finished(run_dir, "datagate", 7) == []
    import tarfile
    assert sorted(tarfile.open(tgz).getnames())[:2] == ["checkpoint_1", "checkpoint_1/evaluation.json"]


def test_unknown_reading_never_waits_and_is_skipped_in_costs():
    now = datetime.datetime(2026, 9, 2, 21, 0, tzinfo=UTC)
    assert ext.seconds_until_room({"five_hour": None}, 30, now) == 0
    records = [{"checkpoint": 1, "phase": "before", "five_hour": None}, rec(1, "after", 40), rec(2, "before", 40), rec(2, "after", 46)]
    assert ext.window_costs(records) == [6]
    assert ext.pct({"five_hour": None}) == "unknown"


def test_usage_retries_then_gives_up(monkeypatch):
    calls = []
    def run(cmd, **kw):
        calls.append(cmd); return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="HTTP Error 502")
    monkeypatch.setattr(subprocess, "run", run); monkeypatch.setattr(ext.time, "sleep", lambda s: None)
    assert ext.usage(attempts=3, pause=0) is None
    assert len(calls) == 3


def test_an_errored_checkpoint_is_not_finished_and_is_next_to_run(tmp_path):
    finished_checkpoint(tmp_path, 1); finished_checkpoint(tmp_path, 2, had_error=True); finished_checkpoint(tmp_path, 3)
    assert not ext.finished(tmp_path, 2) and ext.finished(tmp_path, 1)
    assert ext.next_checkpoint(tmp_path, 7) == 2


def test_repair_never_marks_an_errored_checkpoint_ran(tmp_path):
    finished_checkpoint(tmp_path, 1, had_error=True)
    write_run_info(tmp_path, {"checkpoint_1": "error"})
    assert ext.repair_run_info(tmp_path, 7) == []
    assert yaml.safe_load((tmp_path / "run_info.yaml").read_text())["summary"]["checkpoints"] == {"checkpoint_1": "error"}


def test_unreadable_inference_result_counts_as_errored(tmp_path):
    d = tmp_path / "checkpoint_1"; d.mkdir(); (d / "evaluation.json").write_text("{}"); (d / "inference_result.json").write_text(""); (d / "snapshot").mkdir()
    assert ext.agent_errored(d) and not ext.finished_dir(d)
