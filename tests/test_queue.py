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
    monkeypatch.setattr(q, "CACHE", cat)
    p = tmp_path / "just-solve-xjq-opus5.yaml"; p.write_text("problems:\n  - xjq\n")
    assert q.job_for(p)[1][-1] == "5"


def test_versioned_config_reads_its_own_problems_root(tmp_path):
    root = tmp_path / "specs" / "v2" / "problems"; (root / "datagate").mkdir(parents=True)
    for i in range(1, 8): (root / "datagate" / f"checkpoint_{i}.md").write_text("")
    p = tmp_path / "spectest-v9-specv2-datagate-opus5.yaml"
    p.write_text(f"# header\n#   SCBENCH_PROBLEMS_PATH={root} bin/scb-extend --new x datagate 7\nproblems:\n  - datagate\n")
    label, argv, env = q.job_for(p)
    assert (label, argv[-1], env) == ("spectest-v9-specv2-datagate", "7", {"SCBENCH_PROBLEMS_PATH": str(root)})


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


def test_resume_job_continues_from_the_next_checkpoint(tmp_path, monkeypatch):
    run = tmp_path / "dev6-x" / "fable-5-1_2.1.251_high_just-solve" / "20260905T0532"
    (run / "sith" / "checkpoint_1").mkdir(parents=True); (run / "sith" / "checkpoint_2").mkdir()
    (run / "config.yaml").write_text("problems:\n- sith\n")
    cat = tmp_path / "catalog" / "sith"; cat.mkdir(parents=True)
    for i in range(1, 7): (cat / f"checkpoint_{i}.md").write_text("spec")
    (run / "problem_catalog.json").write_text('{"version": "v1.0", "commit": "abc"}')
    monkeypatch.setattr(q, "CACHE", cat.parent)
    label, argv, env = q.resume_job(run)
    assert label == "fable-5-1_2.1.251_high_just-solve-sith-resume-from-3"
    assert argv[1:] == [str(run), "sith", "6"]
    assert env == {}


def test_next_priority_is_one_above_the_highest_queued():
    tasks = {"1": {"status": {"Running": {}}, "priority": 9}, "2": {"status": "Queued", "priority": 0}, "3": {"status": "Queued", "priority": 2}}
    assert q.next_priority(tasks) == 3
    assert q.next_priority({"1": {"status": "Done"}}) == 1


def test_swap_plan_walks_the_job_to_just_before_the_target():
    assert q.swap_plan([25, 26, 27, 28], 28, 26) == [(28, 27), (27, 26)]
    assert q.swap_plan([25, 26, 27, 28], 25, 28) == [(25, 26), (26, 27)]
    assert q.swap_plan([25, 26, 27, 28], 26, 27) == []
    assert q.swap_plan([25, 26, 27, 28], 27, 27) == []


def test_resume_job_keeps_the_versioned_root_the_run_read(tmp_path):
    run = tmp_path / "spectest" / "opus-5_2.1.251_high_spectest-v9-specv2" / "20260906T0000"
    (run / "datagate" / "checkpoint_1").mkdir(parents=True)
    (run / "config.yaml").write_text("problems:\n- datagate\n")
    root = tmp_path / "specs" / "v2" / "problems"; (root / "datagate").mkdir(parents=True)
    for i in range(1, 8): (root / "datagate" / f"checkpoint_{i}.md").write_text("")
    (run / "problem_catalog.json").write_text('{"version": "env-override", "commit": "%s"}' % root)
    label, argv, env = q.resume_job(run)
    assert argv[1:] == [str(run), "datagate", "7"] and env == {"SCBENCH_PROBLEMS_PATH": str(root)}
