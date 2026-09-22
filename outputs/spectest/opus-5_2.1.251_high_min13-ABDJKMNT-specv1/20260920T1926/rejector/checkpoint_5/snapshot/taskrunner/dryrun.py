"""`--dry-run`: what a run would cost, without sending anything.

Estimates are deliberately coarse: an average prompt word count scaled to
tokens, `max_tokens` assumed for every completion, and a worst-case attempt
count per row for the wall-clock estimate.
"""

from __future__ import annotations

from typing import Any, Sequence

from .config import REJECTION, TaskConfig
from .generation import plan_attempts
from .icl import examples_for, select_setup
from .prompts import render_messages
from .runner import TaskJob

# The dry run's own word-to-token ratio, as the spec states it.
TOKENS_PER_WORD = 1.33


def estimate_run(jobs: Sequence[TaskJob]) -> dict[str, Any]:
    """The estimate JSON printed instead of running the tasks."""
    tasks = {job.name: _task_estimate(job) for job in jobs}
    return {
        "tasks": tasks,
        "total_inputs": sum(task["inputs"] for task in tasks.values()),
        "est_total_tokens": sum(task["est_total_tokens"] for task in tasks.values()),
        "est_total_cost": sum(task["est_cost"] for task in tasks.values()),
        "est_time_minutes": sum(_minutes(job) for job in jobs),
    }


def _task_estimate(job: TaskJob) -> dict[str, Any]:
    config = job.config
    prompt_tokens = round(len(job.rows) * _average_words(job) * TOKENS_PER_WORD)
    completion_tokens = len(job.rows) * config.generation.max_tokens
    return {
        "inputs": len(job.rows),
        "est_prompt_tokens": prompt_tokens,
        "est_completion_tokens": completion_tokens,
        "est_total_tokens": prompt_tokens + completion_tokens,
        "est_cost": _cost(config, prompt_tokens, completion_tokens),
    }


def _average_words(job: TaskJob) -> float:
    """Words in one rendered prompt, averaged over the task's input rows."""
    if not job.rows:
        return 0.0
    plan = plan_attempts(job.config)
    examples = examples_for(job.config.icl, select_setup(job.config.icl, plan.strategy, 0))
    rendered = [render_messages(job.config.prompt, row, examples) for row in job.rows]
    words = [sum(len(message["content"].split()) for message in messages) for messages in rendered]
    return sum(words) / len(words)


def _cost(config: TaskConfig, prompt_tokens: int, completion_tokens: int) -> float:
    if config.cost is None:
        return 0.0
    return (
        prompt_tokens / 1000 * config.cost.prompt_cost_per_1k
        + completion_tokens / 1000 * config.cost.completion_cost_per_1k
    )


def _minutes(job: TaskJob) -> float:
    """Wall time at the task's request budget, assuming worst-case attempts."""
    rpm = job.config.limits.rpm
    if not rpm:
        return 0.0
    return len(job.rows) * _attempts(job.config) / rpm


def _attempts(config: TaskConfig) -> int:
    """Requests one row may need: `n` for rejection, one for every other scheme."""
    return config.generation.n if config.generation.scheme == REJECTION else 1
