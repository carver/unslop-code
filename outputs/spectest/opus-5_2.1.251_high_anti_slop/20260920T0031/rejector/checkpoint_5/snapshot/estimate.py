"""The `--dry-run` estimate: what a plan would spend before any request is made."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from cost import CostConfig
from plan import TaskRun
from schedule import attempt_plan

#: Prompt tokens per word, the rule of thumb the estimate is built on.
TOKENS_PER_WORD = 1.33


def estimate(runs: Sequence[TaskRun]) -> dict[str, Any]:
    """Per-task token and cost estimates, plus the run totals they add up to."""
    tasks = {run.task.name: _task_estimate(run) for run in runs}
    return {
        "tasks": tasks,
        "total_inputs": sum(task["inputs"] for task in tasks.values()),
        "est_total_tokens": sum(task["est_total_tokens"] for task in tasks.values()),
        "est_total_cost": round(sum(task["est_cost"] for task in tasks.values()), 2),
        "est_time_minutes": round(sum(_minutes(run) for run in runs), 1),
    }


def _task_estimate(run: TaskRun) -> dict[str, Any]:
    """One task's rows sized from its own rendered prompts and its completion budget."""
    inputs = len(run.rows)
    prompt_tokens = round(_average_words(run) * TOKENS_PER_WORD * inputs)
    completion_tokens = inputs * run.task.generation.max_tokens
    return {
        "inputs": inputs,
        "est_prompt_tokens": prompt_tokens,
        "est_completion_tokens": completion_tokens,
        "est_total_tokens": prompt_tokens + completion_tokens,
        "est_cost": round(_cost(run.task.cost, prompt_tokens, completion_tokens), 2),
    }


def _cost(config: CostConfig | None, prompt_tokens: int, completion_tokens: int) -> float:
    return sum(config.of(prompt_tokens, completion_tokens)) if config is not None else 0.0


def _average_words(run: TaskRun) -> float:
    """Words in the average rendered prompt of a task."""
    counts = [sum(len(str(message["content"]).split()) for message in prompt) for prompt in run.prompts]
    return sum(counts) / len(counts) if counts else 0.0


def _minutes(run: TaskRun) -> float:
    """Wall-clock minutes a task needs at its request budget, planning for the worst case.

    Greedy and sampling rows spend one attempt each; a rejection row is counted
    with its whole attempt budget.
    """
    rpm = run.task.limits.rpm
    if not rpm:
        return 0.0
    return len(run.rows) * attempt_plan(run.task, run.setups).limit / rpm
