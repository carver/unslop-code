"""bin/ledger-row: misses keyed by origin checkpoint, with the checkpoints they failed at."""
import json
import sys
import types
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "ledger-row"
lr = types.ModuleType("ledger_row"); lr.__file__ = str(SCRIPT); sys.modules["ledger_row"] = lr
exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), lr.__dict__)


def test_failures_track_origin_and_every_checkpoint_failed_at(tmp_path):
    (tmp_path / "checkpoint_1").mkdir(); (tmp_path / "checkpoint_2").mkdir()
    (tmp_path / "checkpoint_1" / "evaluation.json").write_text(json.dumps({"tests": {"checkpoint_1-Core": {"failed": ["T::a"]}}}))
    (tmp_path / "checkpoint_2" / "evaluation.json").write_text(json.dumps({"tests": {"checkpoint_1-Regression": {"failed": ["T::a"]}, "checkpoint_2-Core": {"failed": ["T::b"]}}}))
    assert lr.failures(tmp_path) == {(1, "T::a"): [1, 2], (2, "T::b"): [2]}
