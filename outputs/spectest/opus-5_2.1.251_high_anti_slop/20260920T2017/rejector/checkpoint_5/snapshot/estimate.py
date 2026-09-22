"""The `--dry-run` estimate of what a run would cost and how long it would take.

Nothing is sent: the config and the inputs are validated as usual, and the
rendered prompts of every row are measured to estimate the tokens a run would
spend.
"""

from __future__ import annotations

from typing import Any, Callable

from config import NO_COST, TaskConfig
from jobs import TaskJob
from limits import count_words
from prompts import RenderedPrompt

#: Dry-run estimates read prompts as words, without the token-window rounding.
TOKENS_PER_WORD = 1.33


def estimate_run(jobs: list[TaskJob]) -> dict[str, Any]:
    """Estimate every task's tokens and cost, and the wall-clock time of the run.

    Tasks run concurrently, so the run takes as long as its slowest task; a task
    with no `rpm` to pace it is left out of that estimate.
    """
    tasks = {job.config.name: _estimate_task(job) for job in jobs}
    return {
        "tasks": tasks,
        "total_inputs": sum(task["inputs"] for task in tasks.values()),
        "est_total_tokens": sum(task["est_total_tokens"] for task in tasks.values()),
        "est_total_cost": round(sum(task["est_cost"] for task in tasks.values()), 2),
        "est_time_minutes": round(max((_minutes(job) for job in jobs), default=0.0), 1),
    }


def _estimate_task(job: TaskJob) -> dict[str, Any]:
    """One task's estimate: one prompt and one full completion per input row."""
    inputs = len(job.rows)
    prompt_tokens = round(inputs * _average_words(job.prompts) * TOKENS_PER_WORD)
    completion_tokens = inputs * job.config.generation.max_tokens
    rates = job.config.cost or NO_COST
    cost = (
        prompt_tokens / 1000 * rates.prompt_cost_per_1k
        + completion_tokens / 1000 * rates.completion_cost_per_1k
    )
    return {
        "inputs": inputs,
        "est_prompt_tokens": prompt_tokens,
        "est_completion_tokens": completion_tokens,
        "est_total_tokens": prompt_tokens + completion_tokens,
        "est_cost": round(cost, 2),
    }


def _average_words(prompts: list[RenderedPrompt]) -> float:
    if not prompts:
        return 0.0
    return sum(count_words(prompt.messages()) for prompt in prompts) / len(prompts)


def _minutes(job: TaskJob) -> float:
    """How long one task's requests take to fit through its request budget."""
    rpm = job.config.rate_limits.rpm
    if rpm is None:
        return 0.0
    return len(job.rows) * _ATTEMPTS[job.config.generation.scheme](job.config) / rpm


#: Requests one row makes, which the schemes that retry plan for the worst case.
_ATTEMPTS: dict[str, Callable[[TaskConfig], int]] = {
    "greedy": lambda config: 1,
    "sample": lambda config: 1,
    "rejection": lambda config: (
        config.generation.max_attempts if config.list_output else config.generation.n
    ),
    "agentic": lambda config: config.generation.max_iterations,
}
