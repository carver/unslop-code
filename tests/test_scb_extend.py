"""Checkpoint selection and window-guard tests for bin/scb-extend."""
import datetime
import json
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
