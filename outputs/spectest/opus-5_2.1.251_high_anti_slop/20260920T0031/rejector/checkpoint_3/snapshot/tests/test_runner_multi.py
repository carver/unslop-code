"""Multi-solution schemes, ICL setup selection per attempt and the list output format."""

import asyncio
from dataclasses import replace

from test_runner import EVALUATION, JUDGE_EVALUATION, MESSAGES, ROW, TASK, StubClient, completion, meta

from api import Completion
from config import GenerationConfig
from icl import IclConfig, RenderedSetup
from judge import Judge
from runner import TaskWorker
from schedule import attempt_plan

SETUPS = tuple(
    RenderedSetup(name=name, messages=({"role": "user", "content": name}, {"role": "assistant", "content": "ok"}))
    for name in ("cot", "direct", "terse")
)


def icl(strategy="fixed", setups=2):
    """A task with `setups` ICL setups; the config only has to name the strategy."""
    return IclConfig(setups=(), strategy=strategy, k=None), SETUPS[:setups]


def run(task, client, setups=()):
    worker = TaskWorker(task, client, judge=None, plan=attempt_plan(task, setups))
    return asyncio.run(worker.run_row(ROW, MESSAGES))


def task_for(scheme, num_solutions, strategy="fixed", setups=2, max_attempts=None, evaluation=EVALUATION):
    config, rendered = icl(strategy, setups)
    generation = GenerationConfig(scheme, 0.0 if scheme == "greedy" else 0.8, 64, n=1, max_attempts=max_attempts)
    task = replace(TASK, generation=generation, icl=config, num_solutions=num_solutions, evaluation=evaluation)
    return task, rendered


def setups_used(result):
    return [entry["icl_setup"] for entry in result["meta"]]


def test_icl_messages_sit_between_the_system_and_user_turns():
    task, setups = task_for("sample", num_solutions=1)
    client = StubClient(completion("5"))
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "2 + 3?"}]

    asyncio.run(TaskWorker(task, client, None, attempt_plan(task, setups)).run_row(ROW, messages))
    assert [message["content"] for message in client.prompts[0]] == ["sys", "cot", "ok", "2 + 3?"]


def test_single_solution_with_icl_still_uses_the_list_format():
    task, setups = task_for("sample", num_solutions=1)
    result = run(task, StubClient(completion("5")), setups)

    assert result["output"] == [{"solution": "working\n#### 5", "icl_setup": "cot"}]
    assert result["result"] == {"passed": 1, "failed": 0, "attempts": 1}
    assert result["meta"] == [meta(1, icl_setup="cot", evaluation_passed=True)]


def test_sample_makes_one_request_per_requested_solution():
    task, setups = task_for("sample", num_solutions=3, strategy="round_robin")
    client = StubClient(completion("5", 1), completion("7", 2), completion("5", 3))
    result = run(task, client, setups)

    # Evaluation does not gate a sampled solution: the failing one is kept too.
    assert [entry["icl_setup"] for entry in result["output"]] == ["cot", "direct", "cot"]
    assert result["result"] == {"passed": 2, "failed": 1, "attempts": 3}
    assert client.calls == [("gpt-4", 0.8, 64)] * 3


def test_sample_without_icl_repeats_the_same_prompt():
    task = replace(TASK, generation=GenerationConfig("sample", 0.8, 64, n=1), num_solutions=2)
    client = StubClient(completion("5", 1), completion("5", 2))
    result = run(task, client)

    assert setups_used(result) == [None, None]
    assert result["output"] == [{"solution": "working\n#### 5", "icl_setup": None}] * 2
    assert client.prompts == [MESSAGES, MESSAGES]


def test_greedy_walks_every_setup_once():
    task, setups = task_for("greedy", num_solutions=5, strategy="random", setups=3)
    client = StubClient(*(completion("5", index) for index in range(1, 4)))
    result = run(task, client, setups)

    # Five solutions were asked for, but a setup is deterministic, so each is used once.
    assert setups_used(result) == ["cot", "direct", "terse"]
    assert result["result"] == {"passed": 3, "failed": 0, "attempts": 3}
    assert client.calls == [("gpt-4", 0.0, 64)] * 3


def test_greedy_stops_once_it_has_the_solutions_it_wants():
    task, setups = task_for("greedy", num_solutions=2, setups=3)
    result = run(task, StubClient(completion("5", 1), completion("5", 2)), setups)
    assert setups_used(result) == ["cot", "direct"]


def test_rejection_collects_several_passing_solutions():
    task, setups = task_for("rejection", num_solutions=2, strategy="round_robin", max_attempts=6)
    client = StubClient(completion("7", 1), completion("5", 2), completion("7", 3), completion("5", 4))
    result = run(task, client, setups)

    assert result["output"] == [
        {"solution": "working\n#### 5", "icl_setup": "direct"},
        {"solution": "working\n#### 5", "icl_setup": "direct"},
    ]
    assert result["result"] == {"passed": 2, "failed": 2, "attempts": 4}
    assert setups_used(result) == ["cot", "direct", "cot", "direct"]


def test_rejection_writes_the_solutions_it_managed_to_collect():
    task, setups = task_for("rejection", num_solutions=5, max_attempts=10)
    responses = [completion("5" if index in (3, 6) else "7", index) for index in range(1, 11)]
    result = run(task, StubClient(*responses), setups)

    assert len(result["output"]) == 2
    assert result["result"] == {"passed": 2, "failed": 8, "attempts": 10}


def test_rejection_without_icl_keeps_the_same_prompt_for_every_attempt():
    generation = GenerationConfig("rejection", 0.8, 64, n=1, max_attempts=4)
    task = replace(TASK, generation=generation, num_solutions=2)
    result = run(task, StubClient(completion("5", 1), completion("7", 2), completion("5", 3)))

    assert result["result"] == {"passed": 2, "failed": 1, "attempts": 3}
    assert setups_used(result) == [None, None, None]


def test_unevaluated_solutions_count_as_passed_without_a_verdict():
    task, setups = task_for("sample", num_solutions=2, evaluation=None)
    result = run(task, StubClient(completion("5", 1), completion("7", 2)), setups)

    assert result["result"] == {"passed": 2, "failed": 0, "attempts": 2}
    assert [entry["evaluation_passed"] for entry in result["meta"]] == [None, None]


def test_an_unanswered_attempt_counts_as_a_failure():
    task, setups = task_for("sample", num_solutions=3, evaluation=None)
    result = run(task, StubClient(completion("5", 1), None, completion("5", 3)), setups)

    assert result["result"] == {"passed": 1, "failed": 1, "attempts": 2}
    assert len(result["meta"]) == 1


def test_a_judged_attempt_reports_its_judge_call_alongside_the_setup():
    task, setups = task_for("sample", num_solutions=1, evaluation=JUDGE_EVALUATION)
    client = StubClient(completion("5"), Completion(text="8", meta=meta(2)))
    worker = TaskWorker(task, client, Judge(client, JUDGE_EVALUATION, max_tokens=64), attempt_plan(task, setups))
    result = asyncio.run(worker.run_row(ROW, MESSAGES))

    assert result["result"] == {"passed": 1, "failed": 0, "attempts": 1}
    assert result["meta"] == [meta(1, judge_meta=meta(2), icl_setup="cot", evaluation_passed=True)]


def test_a_task_without_icl_asking_for_one_solution_keeps_the_part_1_format():
    result = run(TASK, StubClient(completion("5")))
    assert result["output"] == {"solution": "working\n#### 5"}
    assert result["meta"] == meta(1)


def test_a_legacy_rejection_task_spends_n_attempts_and_ignores_max_attempts():
    generation = GenerationConfig("rejection", 0.8, 64, n=2, max_attempts=10)
    client = StubClient(*(completion("7", index) for index in range(1, 11)))
    result = run(replace(TASK, generation=generation), client)

    assert result["result"] == {"passed": False, "extracted_answer": None, "attempts": 2}
    assert len(client.calls) == 2
