"""`num_solutions`: attempt budgets per scheme, `max_attempts`, and the flags."""

from __future__ import annotations

from fake_server import FakeAPIServer, Reply, always, assistants_of, completion
from conftest import GSM8K_TASK, base_config, icl_config, icl_setup, multi_config

ROW = {"question": "q", "answer": "5"}
PASS = "#### 5"
FAIL = "#### 0"


def _passes_on(*indices):
    """Responder whose attempts at `indices` pass exact_match; the rest fail."""

    def responder(payload, index):
        return Reply(completion(PASS if index in indices else FAIL))

    return responder


def _run(write_config, write_input, run_cli, config_map, *extra, responder=None, rows=None):
    with FakeAPIServer(responder or always(PASS)) as api:
        config_map["task"]["api_url"] = api.url
        result = run_cli(write_config(config_map), write_input(rows or [ROW]), *extra)
        result.payloads = api.payloads
    return result


def _sampling(config_map, num_solutions, **generation):
    config_map["task"]["generation"] = {
        "scheme": "sample", "temperature": 0.7, "max_tokens": 64, **generation
    }
    config_map["task"]["num_solutions"] = num_solutions
    return config_map


def _rejection(config_map, num_solutions, **generation):
    config_map["task"]["generation"] = {
        "scheme": "rejection", "temperature": 0.7, "max_tokens": 64, **generation
    }
    config_map["task"]["num_solutions"] = num_solutions
    return config_map


# Spec: "greedy with ICL: generate at temperature 0 once per selected setup"
def test_greedy_with_icl_generates_once_per_setup_at_temperature_zero(write_config, write_input, run_cli):
    config_map = icl_config("", [icl_setup("A", "A-1"), icl_setup("B", "B-1")])
    config_map["task"]["num_solutions"] = 2
    result = _run(write_config, write_input, run_cli, config_map)

    assert len(result.payloads) == 2
    assert [payload["temperature"] for payload in result.payloads] == [0.0, 0.0]
    assert len(result.rows[0]["output"]) == 2


# Spec: "the maximum number of produced solutions is the number of available
# setups" - the worked greedy cap example
def test_greedy_produces_at_most_one_solution_per_setup(write_config, write_input, run_cli):
    config_map = icl_config("", [icl_setup("A", "A-1"), icl_setup("B", "B-1")])
    config_map["task"]["num_solutions"] = 5
    result = _run(write_config, write_input, run_cli, config_map)

    assert len(result.payloads) == 2
    assert len(result.rows[0]["output"]) == 2
    assert result.rows[0]["result"]["attempts"] == 2


# Spec: "stop when num_solutions solutions are collected" - fewer setups used
# than declared when the request is already satisfied
def test_greedy_stops_once_enough_solutions_are_collected(write_config, write_input, run_cli):
    setups = [icl_setup("A", "A-1"), icl_setup("B", "B-1"), icl_setup("C", "C-1")]
    config_map = icl_config("", setups)
    config_map["task"]["num_solutions"] = 2
    result = _run(write_config, write_input, run_cli, config_map)
    assert len(result.payloads) == 2


# Spec: "greedy" without ICL cannot vary its output (see AMBIGUITIES T38)
def test_greedy_without_icl_produces_one_solution(write_config, write_input, run_cli):
    config_map = base_config("")
    config_map["task"]["num_solutions"] = 4
    result = _run(write_config, write_input, run_cli, config_map)

    assert len(result.payloads) == 1
    assert len(result.rows[0]["output"]) == 1


# Spec: "sample with ICL: make one sampled generation per requested solution
# using the chosen ICL strategy"
def test_sample_with_icl_makes_one_generation_per_solution(write_config, write_input, run_cli):
    config_map = icl_config("", [icl_setup("A", "A-1"), icl_setup("B", "B-1")], strategy="round_robin")
    result = _run(write_config, write_input, run_cli, _sampling(config_map, 3))

    assert len(result.payloads) == 3
    assert len(result.rows[0]["output"]) == 3


# Spec: "evaluation does not gate whether a solution is included"
def test_sample_keeps_failing_solutions(write_config, write_input, run_cli):
    config_map = icl_config("", [icl_setup("A", "A-1")])
    result = _run(
        write_config, write_input, run_cli, _sampling(config_map, 3), responder=_passes_on(1)
    )

    row = result.rows[0]
    assert len(row["output"]) == 3
    assert row["result"] == {"passed": 1, "failed": 2, "attempts": 3}


# Spec: "sample without ICL: make num_solutions independent sampled requests"
def test_sample_without_icl_repeats_the_same_prompt(write_config, write_input, run_cli):
    config_map = _sampling(base_config(""), 4)
    result = _run(write_config, write_input, run_cli, config_map)

    assert len(result.payloads) == 4
    assert all(payload["messages"] == result.payloads[0]["messages"] for payload in result.payloads)
    assert all(assistants_of(payload) == [] for payload in result.payloads)


# Spec: "rejection with ICL: keep generating and evaluating until
# num_solutions passing solutions have been collected"
def test_rejection_stops_once_enough_solutions_pass(write_config, write_input, run_cli):
    setups = [icl_setup("A", "A-1"), icl_setup("B", "B-1"), icl_setup("C", "C-1")]
    config_map = icl_config("", setups, strategy="round_robin")
    result = _run(
        write_config,
        write_input,
        run_cli,
        _rejection(config_map, 2, max_attempts=10),
        responder=_passes_on(2, 4),
    )

    row = result.rows[0]
    assert len(result.payloads) == 5
    assert row["result"] == {"passed": 2, "failed": 3, "attempts": 5}
    assert [item["icl_setup"] for item in row["output"]] == ["C", "B"]


# Spec: "rejection without ICL: same as above, but every attempt uses the
# same prompt"
def test_rejection_without_icl_reuses_one_prompt(write_config, write_input, run_cli):
    config_map = _rejection(base_config(""), 2, max_attempts=10)
    result = _run(write_config, write_input, run_cli, config_map)

    assert len(result.payloads) == 2
    assert result.payloads[0]["messages"] == result.payloads[1]["messages"]


# Spec: "max_attempts applies to rejection sampling in this part"
def test_rejection_stops_at_max_attempts(write_config, write_input, run_cli):
    config_map = _rejection(base_config(""), 5, max_attempts=4)
    result = _run(write_config, write_input, run_cli, config_map, responder=always(FAIL))

    assert len(result.payloads) == 4
    assert result.rows[0]["result"]["attempts"] == 4


# Spec: "if max_attempts is omitted for rejection, default it to
# 3 * num_solutions"
def test_max_attempts_defaults_to_three_per_solution(write_config, write_input, run_cli):
    config_map = _rejection(base_config(""), 2)
    result = _run(write_config, write_input, run_cli, config_map, responder=always(FAIL))

    assert len(result.payloads) == 6
    assert result.rows[0]["result"]["attempts"] == 6


# Spec: "legacy compatibility: when num_solutions == 1 and no ICL is
# configured, keep the Part 1 rejection behavior (generation.n logical
# attempts) and do not apply max_attempts"
def test_legacy_rejection_uses_n_and_ignores_max_attempts(write_config, write_input, run_cli):
    config_map = base_config("")
    config_map["task"]["generation"] = {
        "scheme": "rejection", "temperature": 0.7, "max_tokens": 64, "n": 3, "max_attempts": 1
    }
    result = _run(write_config, write_input, run_cli, config_map, responder=always(FAIL))

    assert len(result.payloads) == 3
    assert result.rows[0]["result"] == {"passed": False, "extracted_answer": None, "attempts": 3}


# Spec: the legacy exception needs both conditions; with ICL the rejection
# budget is max_attempts, not `n` (see AMBIGUITIES T37)
def test_rejection_with_icl_uses_max_attempts_not_n(write_config, write_input, run_cli):
    config_map = icl_config("", [icl_setup("A", "A-1")])
    config_map["task"]["generation"] = {
        "scheme": "rejection", "temperature": 0.7, "max_tokens": 64, "n": 7
    }
    config_map["task"]["num_solutions"] = 1
    result = _run(write_config, write_input, run_cli, config_map, responder=always(FAIL))

    assert len(result.payloads) == 3


# Spec: "--num-solutions <int>" and "CLI flags override config values"
def test_num_solutions_flag_overrides_the_config(write_config, write_input, run_cli):
    config_map = _sampling(base_config(""), 5)
    result = _run(write_config, write_input, run_cli, config_map, "--num-solutions", "2")

    assert len(result.payloads) == 2
    assert len(result.rows[0]["output"]) == 2


# Spec: "--icl-k <int>"
def test_icl_k_flag_overrides_the_config(write_config, write_input, run_cli):
    config_map = icl_config("", [icl_setup("A", "A-1", "A-2", "A-3")], k=3)
    result = _run(write_config, write_input, run_cli, config_map, "--icl-k", "1")
    assert assistants_of(result.payloads[0]) == ["A-1"]


# Spec: "--icl-strategy <fixed|random|round_robin>"
def test_icl_strategy_flag_overrides_the_config(write_config, write_input, run_cli):
    config_map = icl_config("", [icl_setup("A", "A-1"), icl_setup("B", "B-1")], strategy="fixed")
    result = _run(
        write_config, write_input, run_cli, _sampling(config_map, 2), "--icl-strategy", "round_robin"
    )
    assert [assistants_of(p)[0] for p in result.payloads] == ["A-1", "B-1"]


# Spec: ICL flags on a task without an `icl` section are inert
# (see AMBIGUITIES T47)
def test_icl_flags_without_an_icl_section_are_ignored(write_config, write_input, run_cli):
    config_map = _sampling(base_config(""), 2)
    result = _run(
        write_config, write_input, run_cli, config_map, "--icl-strategy", "round_robin", "--icl-k", "2"
    )

    assert result.returncode == 0
    assert all(assistants_of(payload) == [] for payload in result.payloads)


# Spec: "num_solutions may be set in defaults or per task"
def test_num_solutions_in_defaults_applies_to_every_task(write_config, write_input, run_argv):
    tasks = {"gsm8k": {**GSM8K_TASK, "generation": {"scheme": "sample", "temperature": 0.7}}}
    with FakeAPIServer(always(PASS)) as api:
        config = write_config(multi_config(api.url, tasks, num_solutions=3))
        rows = write_input([ROW], name="math.jsonl")
        result = run_argv("--config", config, "--input", f"gsm8k={rows}")
        call_count = len(api.requests)

    assert call_count == 3
    assert len(result.task_rows("gsm8k")[0]["output"]) == 3


# Spec: "num_solutions may be set in defaults or per task" - the task wins
def test_task_num_solutions_overrides_defaults(write_config, write_input, run_argv):
    gsm8k = {**GSM8K_TASK, "generation": {"scheme": "sample", "temperature": 0.7}, "num_solutions": 2}
    with FakeAPIServer(always(PASS)) as api:
        config = write_config(multi_config(api.url, {"gsm8k": gsm8k}, num_solutions=4))
        rows = write_input([ROW], name="math.jsonl")
        result = run_argv("--config", config, "--input", f"gsm8k={rows}")
        call_count = len(api.requests)

    assert call_count == 2
    assert len(result.task_rows("gsm8k")[0]["output"]) == 2


# Spec: `num_solutions` counts solutions, so it must be a positive integer
def test_zero_num_solutions_is_rejected(write_config, write_input, run_cli):
    config_map = _sampling(base_config(""), 0)
    result = _run(write_config, write_input, run_cli, config_map)
    assert result.returncode == 1
