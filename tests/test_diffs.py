"""bin/diffs: a checkpoint's diff.json comes back byte for byte from its snapshots and diff_meta.json."""
import json
import random
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "bin" / "diffs"
mod = types.ModuleType("diffs")
mod.__file__ = str(SCRIPT)
sys.modules["diffs"] = mod
exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), mod.__dict__)
if not mod.harness_available():  # diffs are built by the harness: run these under bin/scb's venv
    pytest.skip(
        "slop_code is not importable here; run with ~/.venvs/scbench-harness/bin/python", allow_module_level=True
    )

from slop_code.execution.snapshot import SnapshotDiff, create_diff_from_directories  # noqa: E402

SNAPSHOTS = [
    {"app.py": "print(1)\n", "README.md": "# app\n"},
    {"app.py": "print(2)\n", "README.md": "# app\n", "tests/test_app.py": "def test(): pass\n"},
    {"app.py": "print(3)\n", "tests/test_app.py": "def test(): pass\n", "notes.md": "todo\n"},
]


def write_original(checkpoint, base, seed):
    """diff.json the way a run writes it: made-up archive checksums and times, files in a shuffled order."""
    diff = json.loads(create_diff_from_directories(base, checkpoint / "snapshot").model_dump_json())
    order = list(diff["file_diffs"])
    random.Random(seed).shuffle(order)
    diff["file_diffs"] = {path: diff["file_diffs"][path] for path in order}
    diff |= {
        "from_checksum": f"{seed:064x}",
        "to_checksum": f"{seed + 1:064x}",
        "from_timestamp": f"2026-08-30T04:0{seed}:51.346772",
        "to_timestamp": f"2026-08-30T05:0{seed}:02.5",
    }
    (checkpoint / "diff.json").write_text(SnapshotDiff.model_validate(diff).model_dump_json())


def make_problem(tmp_path, bases):
    """A problem dir whose checkpoint N diffs against bases[N-1]: "previous" or "empty"."""
    problem = tmp_path / "run" / "xjq"
    previous = None
    for n, (files, base) in enumerate(zip(SNAPSHOTS, bases, strict=True), start=1):
        checkpoint = problem / f"checkpoint_{n}"
        for name, text in files.items():
            (checkpoint / "snapshot" / name).parent.mkdir(parents=True, exist_ok=True)
            (checkpoint / "snapshot" / name).write_text(text)
        write_original(checkpoint, previous if base == "previous" else None, seed=n)
        previous = checkpoint / "snapshot"
    return problem


@pytest.mark.parametrize(
    "bases", [("empty", "previous", "previous"), ("empty", "empty", "empty"), ("empty", "previous", "empty")]
)
def test_rebuild_matches_the_original_bytes(tmp_path, bases):
    problem = make_problem(tmp_path, bases)
    originals = {c: (c / "diff.json").read_bytes() for c in mod.checkpoints(problem)}
    mod.save_meta(problem)
    for checkpoint in originals:
        (checkpoint / "diff.json").unlink()
    mod.rebuild(problem)
    assert {c: (c / "diff.json").read_bytes() for c in originals} == originals


def test_meta_records_the_base_each_checkpoint_used(tmp_path):
    problem = make_problem(tmp_path, ("empty", "previous", "empty"))
    mod.save_meta(problem)
    bases = [json.loads((c / "diff_meta.json").read_text())["base"] for c in mod.checkpoints(problem)]
    assert bases == ["empty", "previous", "empty"]


def test_meta_refuses_a_diff_neither_base_explains(tmp_path):
    problem = make_problem(tmp_path, ("empty", "previous", "previous"))
    (problem / "checkpoint_2" / "snapshot" / "app.py").write_text("print('edited after the run')\n")
    with pytest.raises(SystemExit, match="checkpoint_2"):
        mod.save_meta(problem)


def test_rebuild_refuses_when_the_snapshot_no_longer_matches_the_meta(tmp_path):
    problem = make_problem(tmp_path, ("empty", "previous", "previous"))
    mod.save_meta(problem)
    (problem / "checkpoint_3" / "snapshot" / "extra.py").write_text("x = 1\n")
    with pytest.raises(SystemExit, match="checkpoint_3"):
        mod.rebuild(problem)


def test_checkpoints_sort_by_number_not_name(tmp_path):
    problem = tmp_path / "p"
    for n in (1, 2, 10):
        (problem / f"checkpoint_{n}").mkdir(parents=True)
    (problem / "quality_analysis").mkdir()
    assert [c.name for c in mod.checkpoints(problem)] == ["checkpoint_1", "checkpoint_2", "checkpoint_10"]
