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


def test_state_of_reads_string_and_object_statuses():
    assert q.state_of({"status": "Queued"}) == "Queued"
    assert q.state_of({"status": {"Running": {"start": "x"}}}) == "Running"


def test_descendants_follows_the_ppid_chain():
    table = [(10, 1), (11, 10), (12, 11), (20, 1), (13, 12)]
    assert q.descendants({10}, table) == {10, 11, 12, 13}


def test_job_roots_match_the_config_name_but_never_the_wrapper():
    command = "SCBENCH_PROBLEMS_PATH=/x/problems /x/bin/scb-extend --new /x/configs/runs/spectest-v8-datagate-opus5.yaml datagate 7"
    table = [(100, 1, "sh -c ... bin/scb-extend --new /x/configs/runs/spectest-v8-datagate-opus5.yaml datagate 7"),
             (101, 100, "python3 /x/bin/scb-extend --new /x/configs/runs/spectest-v8-datagate-opus5.yaml datagate 7"),
             (102, 101, "python -c from multiprocessing.spawn import spawn_main"),
             (200, 1, "python3 /x/bin/queue kill 9"),
             (201, 1, "grep spectest-v8-datagate-opus5.yaml somewhere")]
    roots = q.job_roots(command, table, self_pid=999)
    assert roots == {100, 101, 201}
    assert q.descendants(roots, [(p, pp) for p, pp, _ in table]) == {100, 101, 102, 201}


def test_agent_containers_are_the_slop_code_images_only():
    lines = ["2b49508e1981 slop-code:claude_code-2.1.251-python3.12", "98f1e68da179 postgres:16", "bad"]
    assert q.agent_containers(lines) == ["2b49508e1981"]
