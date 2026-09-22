"""bin/queue: a run config becomes one scb-extend job with the right catalog."""
import json
import subprocess
import sys
import time
import types

import pytest
import yaml
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


def test_placed_order_puts_the_new_job_right_before_the_target():
    assert q.placed_order([25, 26, 27], 30, 26) == [25, 30, 26, 27]
    assert q.placed_order([25, 26, 27], 30, 25) == [30, 25, 26, 27]


def test_placed_order_leads_the_queue_when_the_target_started_meanwhile():
    # One job runs at a time, so a target that left the queue took every job ahead of it along.
    assert q.placed_order([27, 28], 30, 26) == [30, 27, 28]
    assert q.placed_order([], 30, 26) == [30]


def test_placement_reads_the_flag_wherever_it_sits():
    assert q.placement(["--before", "26", "c.yaml", "4"]) == ((q.BEFORE, 26), ["c.yaml", "4"])
    assert q.placement(["c.yaml", "--before", "26"]) == ((q.BEFORE, 26), ["c.yaml"])
    assert q.placement(["--next", "c.yaml"]) == ((q.NEXT, None), ["c.yaml"])
    assert q.placement(["run_dir", "--problem", "xjq"]) == ((q.LAST, None), ["run_dir", "--problem", "xjq"])


@pytest.mark.parametrize("args", [["--before"], ["--before", "c.yaml"], ["--next", "--before", "26", "c.yaml"]])
def test_placement_rejects_a_missing_id_and_two_flags(args):
    with pytest.raises(SystemExit):
        q.placement(args)


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


PUEUED = Path.home() / ".local" / "bin" / "pueued"


@pytest.fixture
def private_queue(tmp_path, monkeypatch):
    """A pueue daemon of this test's own, paused so nothing starts; bin/queue finds it through
    PUEUE_CONFIG_PATH and the session's real queue is never touched."""
    if not (PUEUED.exists() and q.PUEUE.exists()):
        pytest.skip("pueue is not installed")
    home = tmp_path / "pueue"
    home.mkdir()
    config = tmp_path / "pueue.yml"
    config.write_text(yaml.safe_dump({"shared": {
        "pueue_directory": str(home), "runtime_directory": str(home),
        "use_unix_socket": True, "unix_socket_path": str(home / "pueue.socket"),
    }}))
    monkeypatch.setenv("PUEUE_CONFIG_PATH", str(config))
    daemon = subprocess.Popen([PUEUED], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            if subprocess.run([q.PUEUE, "pause"], capture_output=True).returncode == 0:
                break
            time.sleep(0.1)
        else:
            pytest.fail("the private pueue daemon did not come up")
        yield
    finally:
        daemon.terminate()
        daemon.wait(timeout=10)


def test_add_before_lands_between_its_neighbours_and_leaves_nothing_stashed(private_queue, capsys):
    first, target, last = (q.add_task(name, ["true"], {}) for name in ("first", "target", "last"))

    new = q.add_placed(("new", ["true"], {}), q.BEFORE, target)

    tasks = q.tasks_now()
    assert q.queued_order(tasks) == [first, new, target, last]
    assert {q.state_of(t) for t in tasks.values()} == {"Queued"}
    order = ((first, "first"), (new, "new"), (target, "target"), (last, "last"))
    printed = [f"{i:>3} Queued   {label}" for i, label in order]
    assert capsys.readouterr().out.splitlines()[-4:] == printed


def test_add_before_a_job_that_is_not_queued_adds_nothing(private_queue):
    only = q.add_task("only", ["true"], {})

    with pytest.raises(SystemExit, match="not queued"):
        q.add_placed(("new", ["true"], {}), q.BEFORE, only + 5)

    assert list(q.tasks_now()) == [str(only)]


def test_add_next_runs_ahead_of_a_reordered_queue(private_queue):
    a, b = q.add_task("a", ["true"], {}), q.add_task("b", ["true"], {})
    q.move_job(b, a)

    new = q.add_placed(("new", ["true"], {}), q.NEXT)

    assert q.queued_order(q.tasks_now()) == [new, b, a]


def test_dependency_reads_after_wherever_it_sits():
    assert q.dependency(["--after", "26", "c.yaml"]) == (26, ["c.yaml"])
    assert q.dependency(["c.yaml", "4", "--after", "26"]) == (26, ["c.yaml", "4"])
    assert q.dependency(["--next", "c.yaml"]) == (None, ["--next", "c.yaml"])


@pytest.mark.parametrize("args", [["--after"], ["--after", "c.yaml"], ["--after", "1", "--after", "2", "c.yaml"]])
def test_dependency_rejects_a_missing_id_and_two_flags(args):
    with pytest.raises(SystemExit):
        q.dependency(args)


def wait_until_settled(ids):
    for _ in range(100):
        tasks = q.tasks_now()
        if all(q.state_of(tasks[str(i)]) == "Done" for i in ids):
            return tasks
        time.sleep(0.1)
    pytest.fail(f"tasks {ids} did not finish")


def test_a_job_added_after_a_failed_one_never_runs_and_the_queue_moves_on(private_queue, tmp_path):
    ran = tmp_path / "ran"
    failing = q.add_task("halts", ["false"], {})
    dependent = q.add_placed(("repeat", ["touch", str(ran)], {}), q.LAST, after=failing)
    behind = q.add_task("behind", ["true"], {})

    subprocess.run([q.PUEUE, "start"], check=True, capture_output=True)
    tasks = wait_until_settled([failing, dependent, behind])

    assert not ran.exists()
    assert "DependencyFailed" in str(tasks[str(dependent)]["status"])
    assert "Success" in str(tasks[str(behind)]["status"])


def test_a_job_added_after_a_successful_one_runs(private_queue, tmp_path):
    ran = tmp_path / "ran"
    first = q.add_task("strict", ["true"], {})
    second = q.add_placed(("repeat", ["touch", str(ran)], {}), q.NEXT, after=first)

    subprocess.run([q.PUEUE, "start"], check=True, capture_output=True)
    wait_until_settled([first, second])

    assert ran.exists()


def test_channel_reads_the_group_wherever_it_sits():
    assert q.channel(["--group", "side", "c.yaml"]) == ("side", ["c.yaml"])
    assert q.channel(["c.yaml", "4", "--group", "spec-work"]) == ("spec-work", ["c.yaml", "4"])
    assert q.channel(["--next", "c.yaml"]) == (None, ["--next", "c.yaml"])


@pytest.mark.parametrize("args", [["--group"], ["--group", "two words"], ["--group", "a", "--group", "b", "c.yaml"]])
def test_channel_rejects_a_missing_or_odd_name_and_two_flags(args):
    with pytest.raises(SystemExit):
        q.channel(args)


def test_order_and_priority_are_read_within_one_channel():
    tasks = {
        "1": {"status": "Queued", "priority": 1, "group": "default"},
        "2": {"status": "Queued", "priority": 9, "group": "side"},
        "3": {"status": "Queued", "priority": 0},  # pueue's older state files carry no group: the default one
        "4": {"status": "Queued", "priority": 2, "group": "side"},
    }
    assert q.queued_order(tasks) == [1, 3]
    assert q.queued_order(tasks, "side") == [2, 4]
    assert q.next_priority(tasks) == 2
    assert q.next_priority(tasks, "side") == 10


def test_a_jobs_containers_are_the_ones_its_docker_exec_processes_name():
    mine, other = "83bbbe85fd46" + "a" * 52, "0123456789ab" + "b" * 52
    table = [
        (10, 1, "python3 bin/scb-extend --new configs/runs/x-opus5.yaml xjq 5"),
        (11, 10, f"docker exec --workdir /workspace --env HOME=/tmp/agent_home {mine} claude -p hello"),
        (20, 1, f"docker exec --workdir /workspace {other} claude -p hello"),
    ]
    assert q.job_containers({10, 11}, table, [mine[:12], other[:12]]) == [mine[:12]]
    assert q.job_containers({10}, table, [mine[:12], other[:12]]) == []  # between agent turns: nothing names one


def test_a_side_channel_runs_beside_the_main_one_and_keeps_its_own_order(private_queue):
    q.ensure_group("side")  # a new pueue group starts unpaused; hold it while the order is built
    subprocess.run([q.PUEUE, "pause", "--all"], check=True, capture_output=True)
    main_job = q.add_task("main", ["sleep", "30"], {})
    side_a = q.add_placed(("side-a", ["sleep", "30"], {}), q.LAST, group="side")
    side_b = q.add_placed(("side-b", ["true"], {}), q.NEXT, group="side")
    side_c = q.add_placed(("side-c", ["true"], {}), q.BEFORE, side_a)

    tasks = q.tasks_now()
    assert [tasks[str(i)]["group"] for i in (main_job, side_a, side_b, side_c)] == ["default", "side", "side", "side"]
    assert q.queued_order(tasks, "side") == [side_b, side_c, side_a]
    assert q.queued_order(tasks) == [main_job]

    subprocess.run([q.PUEUE, "start", "--all"], check=True, capture_output=True)
    for _ in range(100):
        tasks = q.tasks_now()
        if q.state_of(tasks[str(main_job)]) == q.state_of(tasks[str(side_a)]) == "Running":
            break
        time.sleep(0.1)
    else:
        pytest.fail("the two channels did not run side by side")
    subprocess.run([q.PUEUE, "kill", str(main_job), str(side_a)], check=True, capture_output=True)


def test_a_job_cannot_be_placed_before_one_in_another_channel(private_queue):
    main_job = q.add_task("main", ["true"], {})
    with pytest.raises(SystemExit, match="channel"):
        q.add_placed(("side", ["true"], {}), q.BEFORE, main_job, group="side")
    assert list(q.tasks_now()) == [str(main_job)]


def test_a_new_channel_runs_one_job_at_a_time(private_queue):
    q.ensure_group("side")
    q.ensure_group("side")  # asking twice is fine
    groups = json.loads(subprocess.run([q.PUEUE, "status", "--json"], capture_output=True, text=True).stdout)["groups"]
    assert groups["side"]["parallel_tasks"] == 1


def task(state, label, group=None, result=None, end=None):
    status = state if result is None else {state: {"result": result, "end": end or "2026-09-21T10:00:00-07:00"}}
    return {"status": status, "label": label, "command": "cmd", "group": group or "default", "priority": 0}


TASKS = {
    "1": task("Done", "old-success", result="Success", end="2026-09-01T00:00:00-07:00"),
    "2": task("Done", "failed-run", result={"Failed": 2}, end="2026-09-21T09:00:00-07:00"),
    "3": task("Done", "killed-run", result="Killed"),
    "4": task("Running", "the-running-one"),
    "5": task("Queued", "next-up"),
    "6": task("Stashed", "parked"),
    "7": task("Queued", "side-job", group="specpatch"),
}


def test_status_lists_running_queued_and_stashed_per_channel_and_folds_the_done_ones(monkeypatch, capsys):
    monkeypatch.setattr(q, "tasks_now", lambda: TASKS)
    q.print_status()
    assert capsys.readouterr().out.splitlines() == [
        "[default]",
        "  4 Running  the-running-one",
        "  5 Queued   next-up",
        "  6 Stashed  parked",
        "[specpatch]",
        "  7 Queued   side-job",
        "done: 3 (1 Success, 1 Failed, 1 Killed); the last 2:",
        "  3 Killed   killed-run",
        "  2 Failed:2 failed-run",
        "bin/queue --all lists every done job; bin/queue log <id> shows one",
    ]


def test_status_with_all_lists_every_done_job_newest_first(monkeypatch, capsys):
    monkeypatch.setattr(q, "tasks_now", lambda: TASKS)
    q.print_status(all_done=True)
    out = capsys.readouterr().out.splitlines()
    assert out[out.index("done: 3 (1 Success, 1 Failed, 1 Killed):") + 1:] == [
        "  3 Killed   killed-run", "  2 Failed:2 failed-run", "  1 Success  old-success"]


def test_status_on_an_empty_queue_says_so(monkeypatch, capsys):
    monkeypatch.setattr(q, "tasks_now", lambda: {"1": task("Done", "x", result="Success")})
    q.print_status()
    assert capsys.readouterr().out.splitlines()[0] == "nothing running, queued or stashed"
