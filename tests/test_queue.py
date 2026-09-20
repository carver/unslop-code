"""bin/queue: a run config becomes one scb-extend job with the right catalog."""
import sys
import types

import pytest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "queue"
q = types.ModuleType("queue_tool")
q.__file__ = str(SCRIPT)
sys.modules["queue_tool"] = q
exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), q.__dict__)


def write_config(tmp_path, name, patched):
    launch = "SCBENCH_PROBLEMS_PATH=$PWD/problems " if patched else ""
    p = tmp_path / f"{name}-datagate-opus5.yaml"
    p.write_text(
        f"# header\n#   {launch}bin/scb-extend --new configs/runs/x.yaml datagate 7\nproblems:\n  - datagate\n"
    )
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
    cat = tmp_path / "cat"
    (cat / "xjq").mkdir(parents=True)
    for i in range(1, 6):
        (cat / "xjq" / f"checkpoint_{i}.md").write_text("")
    monkeypatch.setattr(q, "CACHE", cat)
    p = tmp_path / "just-solve-xjq-opus5.yaml"
    p.write_text("problems:\n  - xjq\n")
    assert q.job_for(p)[1][-1] == "5"


def test_versioned_config_reads_its_own_problems_root(tmp_path):
    root = tmp_path / "specs" / "v2" / "problems"
    (root / "datagate").mkdir(parents=True)
    for i in range(1, 8):
        (root / "datagate" / f"checkpoint_{i}.md").write_text("")
    p = tmp_path / "spectest-v9-specv2-datagate-opus5.yaml"
    p.write_text(
        f"# header\n#   SCBENCH_PROBLEMS_PATH={root} bin/scb-extend --new x datagate 7\nproblems:\n  - datagate\n"
    )
    label, argv, env = q.job_for(p)
    assert (label, argv[-1], env) == ("spectest-v9-specv2-datagate", "7", {"SCBENCH_PROBLEMS_PATH": str(root)})


def test_state_of_reads_string_and_object_statuses():
    assert q.state_of({"status": "Queued"}) == "Queued"
    assert q.state_of({"status": {"Running": {"start": "x"}}}) == "Running"


def test_descendants_follows_the_ppid_chain():
    table = [(10, 1), (11, 10), (12, 11), (20, 1), (13, 12)]
    assert q.descendants({10}, table) == {10, 11, 12, 13}


def test_job_roots_match_the_config_name_but_never_the_wrapper():
    command = (
        "SCBENCH_PROBLEMS_PATH=/x/problems "
        "/x/bin/scb-extend --new /x/configs/runs/spectest-v8-datagate-opus5.yaml datagate 7"
    )
    table = [
        (100, 1, "sh -c ... bin/scb-extend --new /x/configs/runs/spectest-v8-datagate-opus5.yaml datagate 7"),
        (101, 100, "python3 /x/bin/scb-extend --new /x/configs/runs/spectest-v8-datagate-opus5.yaml datagate 7"),
        (102, 101, "python -c from multiprocessing.spawn import spawn_main"),
        (200, 1, "python3 /x/bin/queue kill 9"),
        (201, 1, "grep spectest-v8-datagate-opus5.yaml somewhere"),
    ]
    roots = q.job_roots(command, table, self_pid=999)
    assert roots == {100, 101, 201}
    assert q.descendants(roots, [(p, pp) for p, pp, _ in table]) == {100, 101, 102, 201}


def test_agent_containers_are_the_slop_code_images_only():
    lines = ["2b49508e1981 slop-code:claude_code-2.1.251-python3.12", "98f1e68da179 postgres:16", "bad"]
    assert q.agent_containers(lines) == ["2b49508e1981"]


def test_resume_job_continues_from_the_next_checkpoint(tmp_path, monkeypatch):
    run = tmp_path / "dev6-x" / "fable-5-1_2.1.251_high_just-solve" / "20260905T0532"
    (run / "sith" / "checkpoint_1").mkdir(parents=True)
    (run / "sith" / "checkpoint_2").mkdir()
    (run / "config.yaml").write_text("problems:\n- sith\n")
    cat = tmp_path / "catalog" / "sith"
    cat.mkdir(parents=True)
    for i in range(1, 7):
        (cat / f"checkpoint_{i}.md").write_text("spec")
    (run / "problem_catalog.json").write_text('{"version": "v1.0", "commit": "abc"}')
    monkeypatch.setattr(q, "CACHE", cat.parent)
    label, argv, env = q.resume_job(run)
    assert label == "fable-5-1_2.1.251_high_just-solve-sith-resume-from-3"
    assert argv[1:] == [str(run), "sith", "6"]
    assert env == {}


def test_next_priority_is_one_above_the_highest_queued():
    tasks = {
        "1": {"status": {"Running": {}}, "priority": 9},
        "2": {"status": "Queued", "priority": 0},
        "3": {"status": "Queued", "priority": 2},
    }
    assert q.next_priority(tasks) == 3
    assert q.next_priority({"1": {"status": "Done"}}) == 1


def test_moved_order_places_the_job_right_before_the_target():
    assert q.moved_order([25, 26, 27, 28], 28, 26) == [25, 28, 26, 27]
    assert q.moved_order([25, 26, 27, 28], 25, 28) == [26, 27, 25, 28]
    assert q.moved_order([25, 26, 27, 28], 26, 27) == [25, 26, 27, 28]
    assert q.moved_order([25, 26, 27, 28], 27, 27) == [25, 26, 27, 28]
    with pytest.raises(SystemExit):
        q.moved_order([25, 26], 27, 25)


def test_priorities_run_the_order_first_to_last_and_leave_zero_free():
    assert q.priorities_for([28, 25, 26]) == {28: 3, 25: 2, 26: 1}


def test_queued_order_is_highest_priority_then_lowest_id():
    tasks = {
        "1": {"status": "Queued", "priority": 0},
        "2": {"status": "Queued", "priority": 5},
        "3": {"status": {"Running": {}}, "priority": 9},
        "4": {"status": "Queued", "priority": 5},
    }
    assert q.queued_order(tasks) == [2, 4, 1]


def test_rewrite_priorities_touches_only_the_named_sections():
    toml = "[7]\nid = 7\ncommand = \"x\"\npriority = 0\n\n[8]\nid = 8\npriority = 3\n"
    assert q.rewrite_priorities(toml, {"7": 12}) == (
        "[7]\nid = 7\ncommand = \"x\"\npriority = 12\n\n[8]\nid = 8\npriority = 3\n"
    )


def test_resume_job_keeps_the_versioned_root_the_run_read(tmp_path):
    run = tmp_path / "spectest" / "opus-5_2.1.251_high_spectest-v9-specv2" / "20260906T0000"
    (run / "datagate" / "checkpoint_1").mkdir(parents=True)
    (run / "config.yaml").write_text("problems:\n- datagate\n")
    root = tmp_path / "specs" / "v2" / "problems"
    (root / "datagate").mkdir(parents=True)
    for i in range(1, 8):
        (root / "datagate" / f"checkpoint_{i}.md").write_text("")
    (run / "problem_catalog.json").write_text('{"version": "env-override", "commit": "%s"}' % root)
    label, argv, env = q.resume_job(run)
    assert argv[1:] == [str(run), "datagate", "7"] and env == {"SCBENCH_PROBLEMS_PATH": str(root)}


def test_strict_job_runs_the_driver_with_the_configs_root(tmp_path, monkeypatch):
    cfg = write_config(tmp_path, "min12-ABDJKMN-specv2", patched=True)
    monkeypatch.setattr(q, "ROOT", tmp_path)
    (tmp_path / "problems" / "datagate").mkdir(parents=True)
    for i in range(1, 8):
        (tmp_path / "problems" / "datagate" / f"checkpoint_{i}.md").write_text("x")
    label, argv, env = q.strict_job(cfg)
    assert label == "min12-ABDJKMN-specv2-datagate-strict"
    assert argv == [str(tmp_path / "bin" / "scb-strict"), str(cfg), "datagate", "7"]
    assert env == {"SCBENCH_PROBLEMS_PATH": str(tmp_path / "problems")}


def test_added_id_is_read_from_pueues_reply_even_with_a_warning_after_it():
    assert q.added_id("New task added (id 129).\nThe group of this task is currently paused!\n") == 129
    assert q.added_id("New task added (id 7).") == 7


def test_solo_plan_stashes_every_other_queued_job():
    tasks = {
        "1": {"status": "Running"},
        "2": {"status": {"Queued": {}}},
        "3": {"status": {"Queued": {}}},
        "4": {"status": {"Stashed": {}}},
        "5": {"status": {"Done": {}}},
    }
    assert q.solo_plan(tasks, 3) == [2]
    assert q.solo_plan(tasks, 2) == [3]


def test_codex_queue_selects_launcher_and_disables_usage(tmp_path, monkeypatch):
    monkeypatch.setattr(q, 'CACHE', tmp_path / 'catalog')
    config = tmp_path / 'sol.yaml'
    config.write_text('model:\n  provider: codex_auth\n  name: gpt-5.6-sol\nproblems: [xjq]\n')
    _, _, env = q.job_for(config, 5)
    assert env['SCB_LAUNCHER'] == str(q.ROOT / 'bin/scb-sol')
    assert env['SCB_USAGE_TRACKING'] == '0'
    assert env['SCBENCH_PROBLEMS_PATH'] == str(tmp_path / 'catalog')


def test_codex_resume_preserves_provider_and_catalog(tmp_path):
    (tmp_path / 'config.yaml').write_text('model:\n  provider: codex_auth\n  name: gpt-5.6-sol\nproblems: [xjq]\n')
    (tmp_path / 'problem_catalog.json').write_text('{"version":"env-override","commit":"/test/catalog"}')
    _, _, env = q.resume_job(tmp_path, 5)
    assert env['SCB_USAGE_TRACKING'] == '0'
    assert env['SCBENCH_PROBLEMS_PATH'] == '/test/catalog'


def multi_problem_run(tmp_path):
    run = tmp_path / "spectest" / "gpt-5.6-sol_0.153.4_high_min12-ABDJKMN-specv2" / "20260909T0454"
    for problem, done in (("file_merger", 2), ("xjq", 3)):
        for i in range(1, done + 1):
            (run / problem / f"checkpoint_{i}").mkdir(parents=True)
    (run / "config.yaml").write_text(
        "model:\n  provider: codex_auth\n  name: gpt-5.6-sol\nproblems: [file_merger, xjq]\n"
    )
    root = tmp_path / "specs" / "xjq" / "v2" / "problems"
    for problem, n in (("file_merger", 4), ("xjq", 5)):
        (root / problem).mkdir(parents=True)
        for i in range(1, n + 1):
            (root / problem / f"checkpoint_{i}.md").write_text("")
    (run / "problem_catalog.json").write_text('{"version": "env-override", "commit": "%s"}' % root)
    return run, root


def test_multi_problem_resume_runs_the_named_problem_alone(tmp_path):
    run, root = multi_problem_run(tmp_path)
    label, argv, env = q.resume_job(run, problem="xjq")
    assert argv == [str(q.ROOT / "bin" / "scb-extend"), str(run), "xjq", "5"]
    assert "file_merger" not in argv and "file_merger" not in label
    assert label.endswith("-xjq-resume-from-4")
    assert env == {
        "SCBENCH_PROBLEMS_PATH": str(root),
        "SCB_LAUNCHER": str(q.ROOT / "bin" / "scb-sol"),
        "SCB_USAGE_TRACKING": "0",
    }


def test_multi_problem_resume_needs_a_problem(tmp_path):
    run, _ = multi_problem_run(tmp_path)
    with pytest.raises(SystemExit, match="requires --problem"):
        q.resume_job(run)


def test_resume_rejects_a_problem_the_run_does_not_have(tmp_path):
    run, _ = multi_problem_run(tmp_path)
    with pytest.raises(SystemExit, match="datagate is not in this run"):
        q.resume_job(run, problem="datagate")


def test_resume_strict_job_drives_scb_strict_from_the_same_plan(tmp_path):
    run, root = multi_problem_run(tmp_path)
    label, argv, env = q.resume_strict_job(run, problem="xjq")
    assert label.endswith("-xjq-resume-from-4-strict")
    assert argv == [str(q.ROOT / "bin" / "scb-strict"), "--resume", str(run), "xjq", "5"]
    assert env["SCBENCH_PROBLEMS_PATH"] == str(root)


def test_job_result_keeps_the_driver_lines_and_names_the_run_dir():
    log = (
        "[09/14/26 10:54:33] INFO 'datagate': progress update\n"
        "STRICT-RUN: checkpoint_1 48/50 infra_fail=false run_dir=/o/spectest/x/20260914T1054\n"
        "STRICT-RUN:   FAIL checkpoint_1-Functionality: TestFunctionality::test_preserves_whitespace\n"
        "STRICT-RUN: HALT after checkpoint_1, not a strict solve\n"
    )
    lines, run_dir = q.job_result(log)
    assert [line.split(":")[0] for line in lines] == ["STRICT-RUN"] * 3
    assert run_dir == "/o/spectest/x/20260914T1054"


def test_job_result_takes_the_last_run_dir_and_strips_the_closing_paren():
    log = (
        "EXTEND: checkpoint_7 380/405 infra_fail=False agent_error=False window 14.0% -> 15.0% 19:48:07Z\n"
        "EXTEND: DONE, 7 checkpoints present (run_dir=/o/spectest/just-solve/20260914T1154) 19:48:07Z\n"
        "EXTEND: next: bin/ledger-row /o/spectest/just-solve/20260914T1154 -> notes/datagate-runs.md\n"
    )
    lines, run_dir = q.job_result(log)
    assert len(lines) == 3
    assert run_dir == "/o/spectest/just-solve/20260914T1154"


def test_job_result_without_driver_lines_names_no_run_dir():
    assert q.job_result("pueue: task 5 has no output\n") == ([], None)


def test_deletable_run_dir_only_for_fresh_runs_under_outputs(tmp_path):
    outputs = tmp_path / "outputs"
    run = outputs / "spectest" / "x" / "20260101T0000"
    run.mkdir(parents=True)
    new = "env bin/scb-extend --new configs/runs/x.yaml xjq 5"
    assert q.deletable_run_dir(str(run), new, outputs)
    assert not q.deletable_run_dir(str(run), "env bin/scb-extend " + str(run) + " xjq 5", outputs)  # a resume
    assert not q.deletable_run_dir(str(tmp_path / "elsewhere"), new, outputs)  # outside outputs/
    assert not q.deletable_run_dir(None, new, outputs)  # the log named no run dir
