"""bin/queue: a run config becomes one scb-extend job with the right catalog."""
import sys
import types
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "queue"
q = types.ModuleType("queue_tool"); q.__file__ = str(SCRIPT); sys.modules["queue_tool"] = q
exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), q.__dict__)


def write_config(tmp_path, name, patched):
    launch = "SCBENCH_PROBLEMS_PATH=$PWD/problems " if patched else ""
    p = tmp_path / f"{name}-datagate-opus5.yaml"
    p.write_text(f"# header\n#   {launch}bin/scb-extend --new configs/runs/x.yaml datagate 7\nproblems:\n  - datagate\n")
    return p


def test_patched_config_gets_the_problems_root_and_label(tmp_path):
    label, argv, env = q.job_for(write_config(tmp_path, "min4-BEG-disambiguated", True), 7)
    assert label == "min4-BEG-disambiguated-datagate"
    assert argv[1:] == ["--new", str(tmp_path / "min4-BEG-disambiguated-datagate-opus5.yaml"), "datagate", "7"]
    assert env == {"SCBENCH_PROBLEMS_PATH": str(q.ROOT / "problems")}


def test_unpatched_config_has_no_override(tmp_path):
    _, _, env = q.job_for(write_config(tmp_path, "spectest-v4", False), 7)
    assert env == {}


def test_checkpoint_count_comes_from_the_catalog(tmp_path, monkeypatch):
    cat = tmp_path / "cat"; (cat / "xjq").mkdir(parents=True)
    for i in range(1, 6): (cat / "xjq" / f"checkpoint_{i}.md").write_text("")
    monkeypatch.setattr(q, "catalog", lambda patched: cat)
    p = tmp_path / "just-solve-xjq-opus5.yaml"; p.write_text("problems:\n  - xjq\n")
    assert q.job_for(p)[1][-1] == "5"
