"""bin/start-slot: two fresh runs of one config never start in the same minute."""
import subprocess
import sys
import time
import types
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "start-slot"
slot = types.ModuleType("start_slot")
slot.__file__ = str(SCRIPT)
sys.modules["start_slot"] = slot
exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), slot.__dict__)


def test_no_earlier_start_means_no_wait():
    assert slot.wait_seconds(None, now=1000.0, gap=120) == 0


def test_a_start_inside_the_gap_waits_out_the_rest_of_it():
    assert slot.wait_seconds(1000.0, now=1030.0, gap=120) == 90
    assert slot.wait_seconds(1000.0, now=1120.0, gap=120) == 0
    assert slot.wait_seconds(1000.0, now=5000.0, gap=120) == 0


def test_a_clock_that_went_backwards_does_not_wait_forever():
    assert slot.wait_seconds(5000.0, now=1000.0, gap=120) == 0


def test_the_slot_is_per_config_name(tmp_path):
    slot.claim(tmp_path, "a-opus5.yaml", gap=120, now=lambda: 1000.0, sleep=lambda s: None)
    assert slot.wait_seconds(slot.last_start(tmp_path, "a-opus5.yaml"), now=1001.0, gap=120) == 119
    assert slot.last_start(tmp_path, "b-opus5.yaml") is None


def test_claim_sleeps_the_gap_out_and_then_records_its_own_start(tmp_path):
    clock, slept = [1000.0], []

    def sleep(seconds):
        slept.append(seconds)
        clock[0] += seconds

    slot.claim(tmp_path, "a.yaml", gap=120, now=lambda: clock[0], sleep=sleep)
    clock[0] += 10
    slot.claim(tmp_path, "a.yaml", gap=120, now=lambda: clock[0], sleep=sleep)
    assert slept == [110]
    assert slot.last_start(tmp_path, "a.yaml") == 1120.0


def test_two_processes_claiming_one_config_start_a_gap_apart(tmp_path):
    env = {"START_SLOT_DIR": str(tmp_path), "START_SLOT_GAP": "2", "PATH": "/usr/bin:/bin"}
    began = time.monotonic()
    procs = [subprocess.Popen([sys.executable, str(SCRIPT), "configs/runs/x-opus5.yaml"], env=env) for _ in range(2)]
    assert [p.wait(timeout=30) for p in procs] == [0, 0]
    assert 2 <= time.monotonic() - began < 10


def write_run_config(path, save_template):
    path.write_text(f"problems:\n  - x\nsave_template: {save_template}\n")
    return path


def test_the_slot_is_the_run_directory_prefix_not_the_config_name(tmp_path):
    # mvvault v1 and rejector v1 under one prompt are two configs and one directory prefix.
    template = "spectest/${model.name}_${agent.version}_${thinking}_min13-ABDJKMNT-specv1/${now:%Y%m%dT%H%M}"
    mvvault = write_run_config(tmp_path / "min13-ABDJKMNT-specv1-mvvault-opus5.yaml", template)
    rejector = write_run_config(tmp_path / "min13-ABDJKMNT-specv1-rejector-opus5.yaml", template)
    other = write_run_config(tmp_path / "just-solve-specv1-mvvault-opus5.yaml",
                             "spectest/${model.name}_${agent.version}_${thinking}_just-solve-specv1/${now:%Y%m%dT%H%M}")
    assert slot.slot_key(mvvault) == slot.slot_key(rejector)
    assert slot.slot_key(other) != slot.slot_key(mvvault)
    assert "/" not in slot.slot_key(mvvault) and "$" not in slot.slot_key(mvvault)


def test_a_config_that_cannot_be_read_falls_back_to_its_name(tmp_path):
    assert slot.slot_key(tmp_path / "missing-opus5.yaml") == "missing-opus5.yaml"
    assert slot.slot_key(write_run_config(tmp_path / "plain.yaml", "outputs/fixed")) == "plain.yaml"
