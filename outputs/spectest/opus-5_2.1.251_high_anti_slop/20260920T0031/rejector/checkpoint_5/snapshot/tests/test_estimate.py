"""The `--dry-run` estimate built from a plan's rows and prompts."""

from dataclasses import replace

from config import GenerationConfig, PromptConfig, TaskConfig
from cost import CostConfig
from estimate import estimate
from limits import RateLimits
from plan import TaskRun

TASK = TaskConfig(
    name="gsm8k",
    api_url="http://localhost:8000",
    model="gpt-4",
    prompt=PromptConfig(system="", user="{question}"),
    generation=GenerationConfig(scheme="greedy", temperature=0.0, max_tokens=100, n=1),
    evaluation=None,
    output_field="solution",
    limits=RateLimits(rpm=60),
    cost=CostConfig(prompt_per_1k=0.01, completion_per_1k=0.03),
)

#: Ten words per prompt, so every row is estimated at 10 * 1.33 prompt tokens.
PROMPT = [{"role": "user", "content": " ".join("word" for _ in range(10))}]


def plan_for(task, rows=4):
    return [TaskRun(task, [{}] * rows, [PROMPT] * rows, (), "out.jsonl")]


def test_tokens_and_cost_come_from_the_prompts_and_the_completion_budget():
    assert estimate(plan_for(TASK))["tasks"]["gsm8k"] == {
        "inputs": 4,
        "est_prompt_tokens": 53,  # 10 words * 1.33 * 4 rows
        "est_completion_tokens": 400,  # max_tokens per row
        "est_total_tokens": 453,
        "est_cost": 0.01,  # 53/1000 * 0.01 + 400/1000 * 0.03
    }


def test_the_run_totals_add_the_tasks_up():
    other = replace(TASK, name="mmlu")
    summary = estimate(plan_for(TASK) + plan_for(other, rows=2))

    assert (summary["total_inputs"], summary["est_total_tokens"]) == (6, 453 + 227)
    assert list(summary["tasks"]) == ["gsm8k", "mmlu"]


def test_greedy_time_is_one_attempt_per_row():
    assert estimate(plan_for(TASK, rows=120))["est_time_minutes"] == 2.0


def test_rejection_time_plans_for_every_attempt():
    task = replace(TASK, generation=GenerationConfig("rejection", 0.7, 100, n=5))
    assert estimate(plan_for(task, rows=120))["est_time_minutes"] == 10.0


def test_a_task_without_a_request_budget_is_left_out_of_the_time():
    assert estimate(plan_for(replace(TASK, limits=RateLimits())))["est_time_minutes"] == 0.0


def test_an_uncosted_task_estimates_no_cost():
    assert estimate(plan_for(replace(TASK, cost=None)))["est_total_cost"] == 0.0
