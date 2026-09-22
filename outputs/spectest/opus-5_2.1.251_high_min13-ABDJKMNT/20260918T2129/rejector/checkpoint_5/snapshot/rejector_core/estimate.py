"""The `--dry-run` estimate: input counts, tokens, cost, and time."""

from __future__ import annotations

from .config import Cost, TaskConfig
from .cost import MONEY_PLACES
from .prompts import build_messages

WORD_TOKEN_FACTOR = 1.33
FALLBACK_RPM = 60


def estimate_run(tasks: list[TaskConfig], rows_by_task: dict) -> dict:
    """Project the whole run without sending a request."""
    estimates = {_key(task): _task_estimate(task, rows_by_task[task.name]) for task in tasks}
    minutes = sum(
        len(rows_by_task[task.name]) * _avg_attempts(task) / (task.rate_limits.rpm or FALLBACK_RPM)
        for task in tasks
    )

    return {
        "tasks": estimates,
        "total_inputs": sum(estimate["inputs"] for estimate in estimates.values()),
        "est_total_tokens": sum(estimate["est_total_tokens"] for estimate in estimates.values()),
        "est_total_cost": round(
            sum(estimate["est_cost"] for estimate in estimates.values()), MONEY_PLACES
        ),
        "est_time_minutes": round(minutes, 1),
    }


def _task_estimate(task: TaskConfig, rows: list[dict]) -> dict:
    """One task's projected token spend, from the average prompt length."""
    words = [_prompt_words(task, row) for row in rows]
    average = sum(words) / len(words) if words else 0.0

    prompt_tokens = round(len(rows) * average * WORD_TOKEN_FACTOR)
    completion_tokens = len(rows) * task.generation.max_tokens
    return {
        "inputs": len(rows),
        "est_prompt_tokens": prompt_tokens,
        "est_completion_tokens": completion_tokens,
        "est_total_tokens": prompt_tokens + completion_tokens,
        "est_cost": round(_cost_of(task.cost, prompt_tokens, completion_tokens), MONEY_PLACES),
    }


def _prompt_words(task: TaskConfig, row: dict) -> int:
    messages = build_messages(task.prompt, row)
    return sum(len(message["content"].split()) for message in messages)


def _cost_of(rates: Cost | None, prompt_tokens: int, completion_tokens: int) -> float:
    if rates is None:
        return 0.0
    return (
        prompt_tokens / 1000 * rates.prompt_cost_per_1k
        + completion_tokens / 1000 * rates.completion_cost_per_1k
    )


def _avg_attempts(task: TaskConfig) -> int:
    """Attempts per row for worst-case planning; only rejection retries."""
    return task.generation.n if task.generation.scheme == "rejection" else 1


def _key(task: TaskConfig) -> str:
    """The estimate's key for a task; Part 1 configs may not name theirs."""
    return task.name or "task"
