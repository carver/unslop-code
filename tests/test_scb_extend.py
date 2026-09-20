"""Checkpoint selection and window-guard tests for bin/scb-extend."""
import datetime
import yaml
import json
import os
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
        d = tmp_path / f"checkpoint_{n}"
        d.mkdir()
        (d / "evaluation.json").write_text(
            json.dumps(
                {
                    "pass_counts": {"Core": 4, "Error": 1},
                    "total_counts": {"Core": 5, "Error": 1},
                    "infrastructure_failure": False,
                }
            )
        )
        (d / "inference_result.json").write_text(json.dumps({"had_error": False}))
        (d / "snapshot").mkdir()
    for n in partial:
        (tmp_path / f"checkpoint_{n}").mkdir()
    return tmp_path


def test_next_checkpoint_is_first_without_evaluation(tmp_path):
    p = make_problem(tmp_path, evaluated=[1, 2], partial=[3])
    assert ext.next_checkpoint(p, 7) == 3


def test_next_checkpoint_none_when_all_evaluated(tmp_path):
    p = make_problem(tmp_path, evaluated=[1, 2])
    assert ext.next_checkpoint(p, 2) is None


def test_infra_failed_checkpoint_is_not_finished(tmp_path):
    """Job 60 on 2026-09-06: the evaluation's pip install hit a DNS error, evaluation.json said 0/0 with
    infrastructure_failure, and the resume guard refused to redo the checkpoint because it looked finished."""
    p = make_problem(tmp_path, evaluated=[1, 2])
    ev = p / "checkpoint_2" / "evaluation.json"
    ev.write_text(json.dumps({**json.loads(ev.read_text()), "infrastructure_failure": True}))
    assert not ext.finished(p, 2)
    assert ext.next_checkpoint(p, 2) == 2


def test_outcome_sums_pass_and_total_counts(tmp_path):
    p = make_problem(tmp_path, evaluated=[1])
    assert ext.outcome(p, 1) == (5, 6, False)
    assert ext.outcome(p, 2) is None


def test_window_costs_pair_readings_within_one_window():
    records = [
        rec(1, "before", 20),
        rec(1, "after", 45),
        rec(2, "before", 45),
        rec(2, "after", 5, resets_at="2026-09-03T02:20:00+00:00"),
        rec(3, "before", 5, resets_at="2026-09-03T02:20:00+00:00"),
        rec(3, "after", 22, resets_at="2026-09-03T02:20:00+00:00"),
    ]
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
    d = problem_dir / f"checkpoint_{n}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "evaluation.json").write_text("{}")
    (d / "inference_result.json").write_text(json.dumps({"had_error": had_error}))
    (d / "snapshot").mkdir()


def write_run_info(problem_dir, states):
    (problem_dir / "run_info.yaml").write_text(
        yaml.safe_dump({"seed": 42, "summary": {"checkpoints": states, "state": "error"}})
    )


def test_repair_marks_finished_checkpoints_ran_and_keeps_a_backup(tmp_path):
    finished_checkpoint(tmp_path, 1)
    finished_checkpoint(tmp_path, 2)
    (tmp_path / "checkpoint_3").mkdir()
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
"""  # noqa: W291  scb prints a trailing space after Completed:


def test_deletions_lists_the_directories_a_preview_would_remove():
    assert ext.deletions(PREVIEW) == [Path("/runs/x/datagate/checkpoint_1"), Path("/runs/x/datagate/checkpoint_2")]


def test_deletions_empty_when_preview_keeps_everything():
    assert (
        ext.deletions(
            "datagate:\n  Resume from: checkpoint_3\n  Completed: checkpoint_1, checkpoint_2\n\n"
            "No changes made (dry run).\n"
        )
        == []
    )


def test_finished_dir_needs_evaluation_result_and_snapshot(tmp_path):
    finished_checkpoint(tmp_path, 1)
    (tmp_path / "checkpoint_2").mkdir()
    (tmp_path / "checkpoint_2" / "prompt.txt").write_text("x")
    assert ext.finished_dir(tmp_path / "checkpoint_1")
    assert not ext.finished_dir(tmp_path / "checkpoint_2")


def test_output_dir_parsed_through_ansi_colour():
    assert ext.output_dir_from("\x1b[32m\x1b[1mOutput directory: /runs/x/20260902T2100\x1b[0m\n") == Path(
        "/runs/x/20260902T2100"
    )
    assert ext.output_dir_from("Output directory: outputs/x/20260902T2100\n") == ext.ROOT / "outputs/x/20260902T2100"
    assert ext.output_dir_from("Starting run...\n") is None


def test_backup_tars_each_finished_checkpoint_once(tmp_path, monkeypatch):
    run_dir = tmp_path / "spectest-v4" / "20260902T2100"
    problem_dir = run_dir / "datagate"
    finished_checkpoint(problem_dir, 1)
    (problem_dir / "checkpoint_2").mkdir()
    write_run_info(problem_dir, {"checkpoint_1": "ran"})
    monkeypatch.setattr(ext, "backup_dir", lambda: tmp_path / "backups")
    assert ext.backup_finished(run_dir, "datagate", 7) == ["checkpoint_1"]
    tgz = tmp_path / "backups" / "spectest-v4-20260902T2100-datagate-checkpoint_1.tgz"
    assert tgz.exists()
    assert ext.backup_finished(run_dir, "datagate", 7) == []
    import tarfile

    with tarfile.open(tgz) as tar:
        assert sorted(tar.getnames())[:2] == ["checkpoint_1", "checkpoint_1/evaluation.json"]


def test_unknown_reading_never_waits_and_is_skipped_in_costs():
    now = datetime.datetime(2026, 9, 2, 21, 0, tzinfo=UTC)
    assert ext.seconds_until_room({"five_hour": None}, 30, now) == 0
    records = [
        {"checkpoint": 1, "phase": "before", "five_hour": None},
        rec(1, "after", 40),
        rec(2, "before", 40),
        rec(2, "after", 46),
    ]
    assert ext.window_costs(records) == [6]
    assert ext.pct({"five_hour": None}) == "unknown"


def test_usage_retries_then_gives_up(monkeypatch):
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="HTTP Error 502")

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(ext.time, "sleep", lambda s: None)
    assert ext.usage(attempts=3, pause=0) is None
    assert len(calls) == 3


def test_an_errored_checkpoint_is_not_finished_and_is_next_to_run(tmp_path):
    finished_checkpoint(tmp_path, 1)
    finished_checkpoint(tmp_path, 2, had_error=True)
    finished_checkpoint(tmp_path, 3)
    assert not ext.finished(tmp_path, 2) and ext.finished(tmp_path, 1)
    assert ext.next_checkpoint(tmp_path, 7) == 2


def test_repair_never_marks_an_errored_checkpoint_ran(tmp_path):
    finished_checkpoint(tmp_path, 1, had_error=True)
    write_run_info(tmp_path, {"checkpoint_1": "error"})
    assert ext.repair_run_info(tmp_path, 7) == []
    assert yaml.safe_load((tmp_path / "run_info.yaml").read_text())["summary"]["checkpoints"] == {
        "checkpoint_1": "error"
    }


def test_unreadable_inference_result_counts_as_errored(tmp_path):
    d = tmp_path / "checkpoint_1"
    d.mkdir()
    (d / "evaluation.json").write_text("{}")
    (d / "inference_result.json").write_text("")
    (d / "snapshot").mkdir()
    assert ext.agent_errored(d) and not ext.finished_dir(d)


def test_overloaded_means_capacity_errors_and_no_tool_use(tmp_path):
    d = tmp_path / "checkpoint_1" / "agent"
    d.mkdir(parents=True)
    (d / "stdout.jsonl").write_text(
        '{"type":"system","error":"overloaded"}\n{"type":"assistant","error":"server_error"}\n'
    )
    assert ext.overloaded(tmp_path / "checkpoint_1")
    (d / "stdout.jsonl").write_text(
        '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash"}]}}\n{"type":"assistant","error":"server_error"}\n'
    )
    assert not ext.overloaded(tmp_path / "checkpoint_1")
    assert not ext.overloaded(tmp_path / "checkpoint_9")


def _record(ckpt, phase, pct, resets="2026-09-05T16:00:00+00:00"):
    return {"checkpoint": ckpt, "phase": phase, "five_hour": {"pct": pct, "resets_at": resets}}


def test_reserve_falls_back_to_prior_runs_then_to_the_default():
    own = [_record("checkpoint_1", "before", 10), _record("checkpoint_1", "after", 18)]
    assert ext.reserve(own, prior=[3.0]) == 10.0
    assert ext.reserve([], prior=[3.0, 4.0]) == 5.0
    assert ext.reserve([], prior=[]) == ext.DEFAULT_RESERVE


def test_prior_costs_reads_the_most_recent_runs_of_the_problem(tmp_path):
    import json

    for i, (a, b) in enumerate([(0, 2), (10, 13), (20, 26)]):
        log = tmp_path / "g" / "p" / f"2026090{i}T0000" / "datagate" / "window_usage.jsonl"
        log.parent.mkdir(parents=True)
        log.write_text(
            "\n".join(
                json.dumps(r) for r in (_record("checkpoint_1", "before", a), _record("checkpoint_1", "after", b))
            )
            + "\n"
        )
        import os

        os.utime(log, (1000 + i, 1000 + i))
    other = tmp_path / "g" / "p" / "20260901T0000" / "xjq" / "window_usage.jsonl"
    other.parent.mkdir(parents=True)
    other.write_text(
        json.dumps(_record("checkpoint_1", "before", 0))
        + "\n"
        + json.dumps(_record("checkpoint_1", "after", 40))
        + "\n"
    )
    assert sorted(ext.prior_costs("datagate", outputs=tmp_path, runs=2)) == [3, 6]
    assert ext.prior_costs("nothing", outputs=tmp_path) == []


def test_window_costs_pairs_readings_despite_reset_time_jitter():
    records = [
        _record("checkpoint_1", "before", 5.0, "2026-09-05T11:09:59.702269+00:00"),
        _record("checkpoint_1", "after", 8.0, "2026-09-05T11:10:00.113741+00:00"),
        _record("checkpoint_2", "before", 8.0, "2026-09-05T11:09:59.513741+00:00"),
        _record("checkpoint_2", "after", 10.0, "2026-09-05T11:09:59.9+00:00"),
    ]
    assert ext.window_costs(records) == [3.0, 2.0]


def test_window_costs_skips_readings_without_a_reset_time():
    records = [_record("checkpoint_1", "before", 0.0, None), _record("checkpoint_1", "after", 3.0)]
    assert ext.window_costs(records) == []


def test_usage_failure_names_the_http_status():
    assert (
        ext.usage_failure('Traceback...\nurllib.error.HTTPError: HTTP Error 429: Too Many Requests\n')
        == "HTTP 429 Too Many Requests"
    )
    assert ext.usage_failure("  func(*args)\nValueError: bad json\n") == "ValueError: bad json"
    assert ext.usage_failure("") == "no output"


def test_usage_backs_off_geometrically_on_429(monkeypatch):
    import types

    calls = []
    monkeypatch.setattr(
        ext.subprocess,
        "run",
        lambda *a, **k: types.SimpleNamespace(returncode=1, stdout="", stderr="HTTP Error 429: Too Many Requests"),
    )
    monkeypatch.setattr(ext.time, "sleep", lambda s: calls.append(s))
    monkeypatch.setattr(ext, "say", lambda msg: None)
    assert ext.usage(attempts=4, pause=30) is None
    assert calls == [30, 60, 120]


def test_usage_disabled_never_launches_usage_command(monkeypatch):
    monkeypatch.setenv('SCB_USAGE_TRACKING', '0')

    def unexpected(*args, **kwargs):
        raise AssertionError('Usage polling must be bypassed')

    monkeypatch.setattr(ext.subprocess, 'run', unexpected)
    assert ext.usage() is None
    assert ext.seconds_until_room({'five_hour': None}, 30, datetime.datetime.now(UTC)) == 0


def test_launcher_override(monkeypatch):
    monkeypatch.setenv('SCB_LAUNCHER', '/test/scb-sol')
    assert ext.launcher() == Path('/test/scb-sol')


def test_quota_halts_before_retry_and_pauses_queue(tmp_path, monkeypatch):
    import pytest

    ck = tmp_path / 'checkpoint_2'
    (ck / 'agent').mkdir(parents=True)
    (ck / 'inference_result.json').write_text('{"had_error":true}')
    (ck / 'agent/stdout.jsonl').write_text(
        json.dumps({'type': 'error', 'message': "You've hit your usage limit. Try again later."}) + '\n'
    )
    calls = []
    monkeypatch.setattr(
        ext.subprocess, 'run', lambda cmd, **kw: (calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, '', ''))
    )
    with pytest.raises(SystemExit) as error:
        ext.halt_on_quota(ck)
    assert error.value.code == 6
    assert calls[0][1:] == ['pause', '--wait', '--all']  # every channel draws on the limit that was hit
    assert (ck / 'inference_result.json').exists()


def test_quota_detection_ignores_solver_text(tmp_path):
    (tmp_path / 'agent').mkdir()
    (tmp_path / 'agent/stdout.jsonl').write_text(
        json.dumps({'type': 'item.completed', 'item': {'text': 'usage limit'}}) + '\n'
    )
    assert ext.quota_error(tmp_path) is None


def test_resume_narrows_to_its_problem_through_the_child_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("SCB_RESUME_ONLY_PROBLEM", raising=False)
    argv, env = ext.resume_command(tmp_path / "run", "xjq", 3)
    assert argv[1:] == ["run", "--resume", str(tmp_path / "run"), "--no-live-progress", "--stop-after-checkpoint", "3"]
    assert env["SCB_RESUME_ONLY_PROBLEM"] == "xjq"
    assert "SCB_RESUME_ONLY_PROBLEM" not in os.environ


def pueue_task(group, start, end=None):
    times = {"start": start} | ({"end": end} if end else {})
    return {"group": group, "status": {"Done" if end else "Running": times}}


def test_overlapping_names_the_other_channels_jobs_that_ran_during_the_checkpoint():
    tasks = {
        "1": pueue_task("default", "2026-09-20T10:00:00.572505675-07:00"),  # this run's own channel
        "2": pueue_task("side", "2026-09-20T10:05:00.000000001-07:00", "2026-09-20T10:20:00-07:00"),  # inside
        "3": pueue_task("side", "2026-09-20T09:00:00-07:00", "2026-09-20T09:30:00-07:00"),  # over before it began
        "4": pueue_task("side", "2026-09-20T10:29:00-07:00"),  # still running at the end
        "5": {"group": "side", "status": {"Queued": {"enqueued_at": "2026-09-20T09:00:00-07:00"}}},
    }
    since, until = "2026-09-20T17:01:00+00:00", "2026-09-20T17:30:00+00:00"
    assert ext.overlapping(tasks, "default", since, until) == [2, 4]
    assert ext.overlapping(tasks, "side", since, until) == [1]
    assert ext.overlapping(tasks, None, since, until) == [1, 2, 4]  # run by hand, outside pueue: every job counts


def test_a_checkpoint_another_channel_overlapped_is_no_measure_of_this_runs_cost():
    records = [
        rec(1, "before", 20),
        rec(1, "after", 60) | {"shared": [7]},
        rec(2, "before", 60),
        rec(2, "after", 72),
    ]
    assert ext.window_costs(records) == [12]
    assert ext.reserve(records) == 15.0
    assert ext.reserve(records[:2], prior=[10]) == 12.5  # nothing of its own to go on: the problem's recent runs
